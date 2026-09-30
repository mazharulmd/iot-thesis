"""Prepare the local stack for a new simulator run.

    python -m tools.prepare_run [--stage local]        (make pipeline-up, e2e and latency call it)

1. Delete telemetry stamped in the future. A run at speed x10 stamps messages up to ten times
   ahead of the wall clock; left in place, those messages sort after the next run's messages, and
   "latest telemetry" queries (playbook prechecks and verification) would read the old run.
2. Delete telemetry older than --keep-hours (default 2). The detector needs 90 s of history and
   playbooks only the latest messages; LocalStack does not expire items by TTL promptly, and a
   table that grows without bound slows DynamoDB down run after run.
3. Release all asset locks and clear the guardrail state (rate limits, circuit breakers):
   incidents from an earlier run own nothing in a new one.
4. Drop shadow commands still queued for the bridge from an earlier run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from common.awsenv import session, stack_outputs
from common.topology import GATEWAYS


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def purge_future_telemetry(table, now: datetime | None = None) -> int:
    return _delete(table, lambda gw: Key("gw").eq(gw) & Key("ts").gt(_iso(now or datetime.now(timezone.utc))))


def trim_old_telemetry(table, keep_hours: float = 2.0, now: datetime | None = None) -> int:
    cutoff = _iso((now or datetime.now(timezone.utc)) - timedelta(hours=keep_hours))
    return _delete(table, lambda gw: Key("gw").eq(gw) & Key("ts").lt(cutoff))


def _delete(table, condition) -> int:
    deleted = 0
    with table.batch_writer() as batch:
        for gw in GATEWAYS:
            kw = {"KeyConditionExpression": condition(gw), "ProjectionExpression": "gw, ts"}
            while True:
                resp = table.query(**kw)
                for item in resp.get("Items", []):
                    batch.delete_item(Key={"gw": item["gw"], "ts": item["ts"]})
                    deleted += 1
                if "LastEvaluatedKey" not in resp:
                    break
                kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return deleted


def drain_queue(sqs, url: str) -> int:
    """Receive and delete everything queued (PurgeQueue is limited to once a minute)."""
    n = 0
    while True:
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=0).get("Messages", [])
        if not msgs:
            return n
        for m in msgs:
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
            n += 1


def prepare(stage: str = "local", keep_hours: float = 2.0) -> dict:
    from .incidents import reset_locks

    sess = session(stage)
    out = stack_outputs(sess, stage)
    ddb = sess.resource("dynamodb")
    telemetry = ddb.Table(out["TelemetryTableName"])
    result = {"future_telemetry_deleted": purge_future_telemetry(telemetry),
              "old_telemetry_deleted": trim_old_telemetry(telemetry, keep_hours)}
    if "LocksTableName" in out:
        result["locks_released"] = reset_locks(ddb.Table(out["LocksTableName"]))
    if "GuardrailsTableName" in out:
        g = ddb.Table(out["GuardrailsTableName"])
        items = g.scan(ProjectionExpression="#k", ExpressionAttributeNames={"#k": "key"}).get("Items", [])
        for item in items:
            g.delete_item(Key={"key": item["key"]})
        result["guardrail_entries_cleared"] = len(items)
    if "ShadowQueueUrl" in out:
        result["queued_shadow_commands_dropped"] = drain_queue(sess.client("sqs"), out["ShadowQueueUrl"])
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", default="local")
    ap.add_argument("--keep-hours", type=float, default=2.0, help="telemetry to keep (hours)")
    args = ap.parse_args()
    res = prepare(args.stage, args.keep_hours)
    print("prepared run: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in res.items()))


if __name__ == "__main__":
    main()
