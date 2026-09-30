"""Detector Lambda: invoked once per gateway message (IoT rule or local bridge).

1. fetch this gateway's previous messages from the Telemetry table
2. run the detection engine (same code as offline evaluation)
3. publish new anomalies to EventBridge and record them in the Detections table
4. update the per-gateway heartbeat, latency and timing statistics

Timing sums (history query, detection, publishing, whole handler) are kept next to the
end-to-end latency so that queueing in front of the Lambda can be told apart from work inside it.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from detection.engine import DetectionEngine
from detection.models import Bundle

PERIOD_S = 10.0
ENGINE = DetectionEngine(Bundle.load(), os.environ.get("DETECTOR", "d2h"))
DDB = boto3.resource("dynamodb")
TELEMETRY = DDB.Table(os.environ["TELEMETRY_TABLE"])
STATS = DDB.Table(os.environ["STATS_TABLE"])
DETECTIONS = DDB.Table(os.environ["DETECTIONS_TABLE"])
EVENTS = boto3.client("events")
BUS = os.environ["EVENT_BUS"]
_cold = True                                  # first call in this container (unless it was a warm-up)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _plain(value):
    """DynamoDB Decimals -> floats/ints, recursively."""
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def history(msg: dict) -> list[dict]:
    """This gateway's previous messages of the same run, oldest first.

    Only messages with the expected sequence numbers (seq-1, seq-2, ...) at the expected times
    (ts - k * 10 s, +/- half a period) are used, so data from an earlier run with overlapping
    timestamps (or a restarted gateway) never mixes into the windows. A gap ends the history.
    """
    need = ENGINE.messages_needed - 1
    now = _parse(msg["ts"])
    seq = int(msg.get("seq", 0))
    lower = _iso(now - timedelta(seconds=PERIOD_S * (need + 1)))
    resp = TELEMETRY.query(KeyConditionExpression=Key("gw").eq(msg["gw"]) & Key("ts").between(lower, msg["ts"]),
                           ScanIndexForward=False)
    by_seq: dict[int, dict] = {}
    for item in resp.get("Items", []):
        k = seq - int(item.get("seq", -1))
        if 1 <= k <= need:
            offset = (now - _parse(item["ts"])).total_seconds() - k * PERIOD_S
            if abs(offset) <= PERIOD_S / 2:
                by_seq.setdefault(k, _plain(item))
    out = []
    for k in range(1, need + 1):
        if k not in by_seq:
            break
        out.append(by_seq[k])
    return list(reversed(out))


def publish(events: list[dict]) -> None:
    for e in events:
        e["detected_at"] = _iso(datetime.now(timezone.utc))
        EVENTS.put_events(Entries=[{
            "Source": "dc.selfheal.detector", "DetailType": "AnomalyDetected",
            "Detail": json.dumps(e), "EventBusName": BUS,
        }])
        DETECTIONS.put_item(Item=json.loads(json.dumps({
            "day": e["ts"][:10], "id": f"{e['ts']}#{e['target']}#{e['fault_type']}",
            **e, "ttl": int(time.time()) + 90 * 86400,
        }), parse_float=Decimal))


def split(msg: dict, start_ms: float) -> dict | None:
    """sent -> bridge -> invoke -> handler start, when the bridge (or IoT rule) stamped the message."""
    if not (msg.get("sent_at") and "bridge_rx_ms" in msg and "bridge_tx_ms" in msg):
        return None
    sent_ms = _parse(msg["sent_at"]).timestamp() * 1000.0
    rx, tx = float(msg["bridge_rx_ms"]), float(msg["bridge_tx_ms"])
    return {"to_bridge": max(0.0, rx - sent_ms), "bridge": max(0.0, tx - rx), "queue": max(0.0, start_ms - tx)}


# Latency histogram buckets (ms, upper bounds): percentiles over any set of gateways and any time
# window come from summing these counters, which DynamoDB can increment atomically.
HIST_EDGES_MS = (25, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000, 30000)


def hist_bucket(latency_ms: float) -> str:
    return next((f"h{e}" for e in HIST_EDGES_MS if latency_ms <= e), "hinf")


def update_stats(msg: dict, now_ms: float, n_events: int, timing: dict, cold: bool,
                 parts: dict | None = None) -> None:
    values = {":one": 1, ":ts": msg.get("ts", ""), ":seq": int(msg.get("seq", 0)), ":seen": int(now_ms),
              ":ev": n_events, ":cold": int(cold),
              **{f":{k}": Decimal(str(round(v, 2))) for k, v in timing.items()}}
    sets = ["last_ts = :ts", "last_seq = :seq", "last_seen_ms = :seen"]
    adds = ["msg_count :one", "detections :ev", "cold_starts :cold",
            "hist_sum_ms :hist", "engine_sum_ms :engine", "publish_sum_ms :publish", "handler_sum_ms :handler"]
    if msg.get("sent_at"):
        values[":lat"] = Decimal(str(round(max(0.0, now_ms - _parse(msg["sent_at"]).timestamp() * 1000.0), 1)))
        sets.append("last_latency_ms = :lat")
        adds += ["latency_sum_ms :lat", f"{hist_bucket(float(values[':lat']))} :one"]
    if parts:
        values.update({f":{k}": Decimal(str(round(v, 2))) for k, v in parts.items()})
        adds += ["stamped_count :one", "to_bridge_sum_ms :to_bridge", "bridge_sum_ms :bridge", "queue_sum_ms :queue"]
    STATS.update_item(Key={"gw": msg["gw"]}, UpdateExpression=f"SET {', '.join(sets)} ADD {', '.join(adds)}",
                      ExpressionAttributeValues=values)


def handler(event, context):
    global _cold
    if event.get("warmup"):                  # pre-warm call: module already loaded the model bundle
        _cold = False
        return {"warm": True, "detector": ENGINE.detector}
    start_ms = time.time() * 1000.0
    t0 = time.perf_counter()
    msgs = history(event) + [event]
    t1 = time.perf_counter()
    found = ENGINE.process(msgs)
    t2 = time.perf_counter()
    publish(found)
    t3 = time.perf_counter()
    timing = {"hist": (t1 - t0) * 1e3, "engine": (t2 - t1) * 1e3, "publish": (t3 - t2) * 1e3,
              "handler": (t3 - t0) * 1e3}
    update_stats(event, time.time() * 1000.0, len(found), timing, _cold,   # latency = gateway send -> detector done
                 split(event, start_ms))
    _cold = False
    return {"gw": event["gw"], "seq": event.get("seq"), "history": len(msgs) - 1,
            "events": [f"{e['fault_type']}:{e['target']}" for e in found],
            "timing_ms": {k: round(v, 1) for k, v in timing.items()}}
