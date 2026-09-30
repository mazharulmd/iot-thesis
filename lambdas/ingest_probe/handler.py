"""Ingest probe Lambda (Step 3 placeholder for the detector).

Invoked once per gateway message. Records, per gateway, how many messages
arrived, the last one seen, and the pipeline latency from gateway to Lambda.
The table doubles as the heartbeat for 'gateway went silent' checks.
"""
import os
import time
from datetime import datetime
from decimal import Decimal

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["STATS_TABLE"])


def _epoch_ms(iso_ts: str) -> float:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).timestamp() * 1000.0


def handler(event, context):
    now_ms = time.time() * 1000.0
    gw = event["gw"]
    names = {"#n": "msg_count"}
    values = {
        ":one": 1,
        ":ts": event.get("ts", ""),
        ":seq": int(event.get("seq", 0)),
        ":seen": int(now_ms),
    }
    update = "SET last_ts = :ts, last_seq = :seq, last_seen_ms = :seen ADD #n :one"
    if event.get("sent_at"):
        latency = max(0.0, now_ms - _epoch_ms(event["sent_at"]))
        values[":lat"] = Decimal(str(round(latency, 1)))
        update = ("SET last_ts = :ts, last_seq = :seq, last_seen_ms = :seen, last_latency_ms = :lat "
                  "ADD #n :one, latency_sum_ms :lat")
    TABLE.update_item(Key={"gw": gw}, UpdateExpression=update,
                      ExpressionAttributeNames=names, ExpressionAttributeValues=values)
    return {"gw": gw, "seq": event.get("seq")}
