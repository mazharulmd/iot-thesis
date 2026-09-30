"""Show pipeline health per gateway:  python -m tools.status [--stage local]"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common.awsenv import session, stack_outputs
from common.topology import GATEWAYS

import re

TIMING_SUMS = ("hist_sum_ms", "engine_sum_ms", "publish_sum_ms", "handler_sum_ms")
HIST_KEY = re.compile(r"^h(\d+|inf)$")


def histogram(item: dict) -> dict:
    """The latency histogram counters of one IngestStats item (h25, h50, ..., hinf)."""
    return {k: int(v) for k, v in item.items() if HIST_KEY.match(k)}


def percentile(hist: dict, q: float) -> float | None:
    """Upper edge (ms) of the bucket holding the q-quantile; inf if it is in the overflow bucket."""
    total = sum(hist.values())
    if total <= 0:
        return None
    edges = sorted(hist, key=lambda k: float("inf") if k == "hinf" else int(k[1:]))
    seen = 0
    for k in edges:
        seen += hist[k]
        if seen >= q * total:
            return float("inf") if k == "hinf" else float(k[1:])
    return float("inf")
SPLIT_SUMS = ("to_bridge_sum_ms", "bridge_sum_ms", "queue_sum_ms")


def gather(stage: str) -> list[dict]:
    sess = session(stage)
    out = stack_outputs(sess, stage)
    ddb = sess.resource("dynamodb")
    stats = {i["gw"]: i for i in ddb.Table(out["IngestStatsTableName"]).scan().get("Items", [])}
    telemetry = ddb.Table(out["TelemetryTableName"])
    rows = []
    now_ms = time.time() * 1000
    for gw in GATEWAYS:
        s = stats.get(gw, {})
        count = int(s.get("msg_count", 0))
        lat_sum = float(s.get("latency_sum_ms", 0))
        stored = telemetry.query(KeyConditionExpression="gw = :g",
                                 ExpressionAttributeValues={":g": gw}, Select="COUNT")["Count"]
        rows.append({
            "gw": gw,
            "stored": stored,
            "lambda_msgs": count,
            "last_seq": int(s.get("last_seq", 0)),
            "seen_s_ago": round((now_ms - float(s["last_seen_ms"])) / 1000, 1) if "last_seen_ms" in s else None,
            "mean_latency_ms": round(lat_sum / count, 1) if count else None,
            "last_latency_ms": float(s["last_latency_ms"]) if "last_latency_ms" in s else None,
            "detections": int(s.get("detections", 0)),
            "latency_sum_ms": lat_sum,
            **{k: float(s.get(k, 0)) for k in TIMING_SUMS + SPLIT_SUMS},
            "stamped_count": int(s.get("stamped_count", 0)),
            "hist": histogram(s),
            "cold_starts": int(s.get("cold_starts", 0)),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Pipeline status")
    ap.add_argument("--stage", default="local")
    args = ap.parse_args()
    rows = gather(args.stage)
    cols = ["gw", "stored", "lambda_msgs", "last_seq", "seen_s_ago", "mean_latency_ms", "last_latency_ms", "detections"]
    print("  ".join(f"{c:>15s}" for c in cols))
    for r in rows:
        print("  ".join(f"{str(r[c] if r[c] is not None else '-'):>15s}" for c in cols))
    shadows = Path(".bridge/shadows.json")
    if shadows.exists():
        docs = json.loads(shadows.read_text())
        print("\nshadows (desired / reported):")
        for gw, doc in docs.items():
            print(f"  {gw}: desired={json.dumps(doc.get('desired'))}  reported={json.dumps(doc.get('reported'))}")


if __name__ == "__main__":
    main()
