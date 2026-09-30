"""Incidents and their audit trail.

    python -m tools.incidents                    list incidents, newest first   (make incidents)
    python -m tools.incidents --id <incident>    one incident, step by step     (make incident I=<id>)
    python -m tools.incidents --locks            current asset locks
    python -m tools.incidents --reset-locks      release every lock (between experiment runs)
    python -m tools.incidents --guardrails       rate-limit and circuit-breaker state
    python -m tools.incidents --reset-breaker A  close the circuit breaker for asset A (after repair)
"""
from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal

from boto3.dynamodb.conditions import Attr, Key

from common.awsenv import session, stack_outputs


def plain(value):
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def guardrails_table(stage: str):
    sess = session(stage)
    out = stack_outputs(sess, stage)
    if "GuardrailsTableName" not in out:
        raise SystemExit("Guardrails table not found; deploy Step 6 first (make deploy-local)")
    return sess.resource("dynamodb").Table(out["GuardrailsTableName"])


def tables(stage: str):
    sess = session(stage)
    out = stack_outputs(sess, stage)
    if "IncidentsTableName" not in out:
        raise SystemExit("Incidents table not found; deploy Step 5 first (make deploy-local)")
    ddb = sess.resource("dynamodb")
    return ddb.Table(out["IncidentsTableName"]), ddb.Table(out["LocksTableName"])


def scan_all(table, **kw) -> list[dict]:
    items, resp = [], table.scan(**kw)
    items += resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kw)
        items += resp.get("Items", [])
    return items


def summaries(incidents, since: str = "") -> list[dict]:
    items = [plain(i) for i in scan_all(incidents, FilterExpression=Attr("sk").eq("A")) if i.get("opened_at", "") >= since]
    return sorted(items, key=lambda i: i.get("opened_at", ""), reverse=True)


def steps(incidents, incident_id: str) -> list[dict]:
    resp = incidents.query(KeyConditionExpression=Key("id").eq(incident_id))
    return sorted((plain(i) for i in resp["Items"] if i["sk"].startswith("L#")), key=lambda i: i["sk"])


def reset_locks(locks) -> int:
    items = scan_all(locks)
    for item in items:
        locks.delete_item(Key={"asset": item["asset"]})
    return len(items)


def main() -> None:
    ap = argparse.ArgumentParser(description="Incidents and locks")
    ap.add_argument("--stage", default="local")
    ap.add_argument("--id")
    ap.add_argument("--locks", action="store_true")
    ap.add_argument("--reset-locks", action="store_true")
    ap.add_argument("-n", type=int, default=20, help="how many incidents to list")
    ap.add_argument("--guardrails", action="store_true")
    ap.add_argument("--reset-breaker")
    args = ap.parse_args()
    incidents, locks = tables(args.stage)

    if args.guardrails:
        now = int(time.time())
        for item in sorted((plain(i) for i in scan_all(guardrails_table(args.stage))), key=lambda i: i["key"]):
            if item["key"].startswith("breaker#"):
                state = "OPEN" if item.get("open_until", 0) > now else "closed"
                print(f"  {item['key']:18s} {state:6s} failures={item['failures']} last={item.get('last_incident')}")
            else:
                recent = {k: v for k, v in item.get("acts", {}).items() if v >= now - 3600}
                print(f"  {item['key']:18s} {len(recent)} automated actions in the last hour")
    elif args.reset_breaker:
        guardrails_table(args.stage).delete_item(Key={"key": f"breaker#{args.reset_breaker}"})
        print(f"circuit breaker for {args.reset_breaker} closed")
    elif args.reset_locks:
        print(f"released {reset_locks(locks)} locks")
    elif args.locks:
        now = int(time.time())
        for item in sorted(scan_all(locks), key=lambda i: i["asset"]):
            left = int(item["expires_at"]) - now
            print(f"  {item['asset']:8s} {item['role']:10s} {item['incident_id']}  "
                  f"{'expires in ' + str(left) + ' s' if left > 0 else 'expired'}")
    elif args.id:
        summary = incidents.get_item(Key={"id": args.id, "sk": "A"}).get("Item")
        if not summary:
            raise SystemExit(f"no incident {args.id}")
        print(json.dumps({k: v for k, v in plain(summary).items() if k != "plan"}, indent=2, default=str))
        for s in steps(incidents, args.id):
            detail = {k: v for k, v in s.items() if k not in ("id", "sk", "step", "at", "event")}
            print(f"  {s['at']}  {s['step']:16s} {json.dumps(detail, default=str)[:220]}")
    else:
        cols = f"{'opened (UTC)':20s} {'status':18s} {'fault':22s} {'target':8s} {'corr':>4s}  id"
        print(cols)
        for i in summaries(incidents)[: args.n]:
            print(f"{i.get('opened_at', '')[:19]:20s} {i.get('status', ''):18s} {i.get('fault_type', ''):22s} "
                  f"{i.get('target', ''):8s} {int(i.get('correlated', 0)):>4d}  {i['id']}")


if __name__ == "__main__":
    main()
