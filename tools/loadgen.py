"""E2: scalability and latency on AWS IoT Core (real AWS only).

    python -m tools.loadgen [--devices 50,500,2000] [--minutes 30] [--warmup 3] [--yes]   (make aws-loadtest)

Each level runs N virtual gateways that publish realistic zone telemetry (recorded from the
simulator) every 10 s over MQTT/TLS to IoT Core, like the real gateways. The whole cloud path runs:
the topic rule stores every message and invokes the detector, which queries history and scores it.
The playbook rule is paused during the test (no incidents or alert emails for virtual gateways)
and re-enabled afterwards.

Measured per level over the window after warm-up:
  * messages sent and processed, loss
  * latency gateway send -> detector done: p50 / p95 / p99 (detector histograms) and its split:
    gateway -> IoT Core (rule timestamp), IoT Core -> Lambda start, inside the handler
  * CloudWatch: Lambda invocations, errors, throttles, duration (avg, p95), peak concurrency;
    DynamoDB write throttles and consumed capacity per message; IoT rule action failures
Results: experiments/results/e2_runs.csv, e2_summary.md, and e2_usage.json (per-message usage
for the cost model). The account's Lambda concurrency limit is read so the 10,000-device level can
be extrapolated.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from boto3.dynamodb.conditions import Attr

from common.awsenv import session, stack_outputs
from common.topology import SITE
from experiments.cost_model import estimate_load_test, load_prices, load_usage
from simulator.config import ScenarioConfig
from simulator.runner import run_scenario

from .status import HIST_KEY, percentile

ROOT = Path(__file__).resolve().parents[1]
CERTS = ROOT / "certs"
RESULTS = ROOT / "experiments" / "results"
PERIOD_S = 10.0
SUMS = ("msg_count", "latency_sum_ms", "stamped_count", "to_bridge_sum_ms", "queue_sum_ms", "handler_sum_ms")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def templates(n: int = 360, seed: int = 4242) -> list[list[dict]]:
    """Zone-gateway telemetry recorded from the simulator: 4 zones x n consecutive messages."""
    msgs = run_scenario(ScenarioConfig(duration_s=n * PERIOD_S, seed=seed), apply_actions=False).messages
    return [[m["assets"] for m in msgs if m["gw"] == f"zone{z}"] for z in range(1, 5)]


class Connection(threading.Thread):
    """One MQTT connection publishing for a group of virtual gateways, spread evenly over the period."""

    def __init__(self, cid: str, devices: list[str], tmpl: list[list[dict]], host: str, stop: threading.Event):
        super().__init__(daemon=True)
        self.devices, self.tmpl, self.stop_event = devices, tmpl, stop
        self.sent = self.failed = 0
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, protocol=mqtt.MQTTv311)
        self.client.tls_set(ca_certs=str(CERTS / "AmazonRootCA1.pem"), certfile=str(CERTS / "device.pem.crt"),
                            keyfile=str(CERTS / "private.pem.key"))
        self.client.reconnect_delay_set(1, 30)
        self.client.connect(host, 8883, keepalive=60)
        self.client.loop_start()

    def run(self) -> None:
        n = len(self.devices)
        seq = [0] * n
        t0 = time.time()
        due = [t0 + PERIOD_S * i / n for i in range(n)]
        while not self.stop_event.is_set():
            i = min(range(n), key=due.__getitem__)
            wait = due[i] - time.time()
            if wait > 0 and self.stop_event.wait(wait):
                break
            seq[i] += 1
            gw = self.devices[i]
            k = int(gw.rsplit("-", 1)[1])                  # stable: device d uses zone d % 4, offset 37 d
            zone = self.tmpl[k % 4]
            now = iso_now()
            msg = {"gw": gw, "ts": now, "seq": seq[i], "sent_at": now,
                   "assets": zone[(seq[i] + 37 * k) % len(zone)]}
            info = self.client.publish(f"{SITE}/{gw}/telemetry", json.dumps(msg), qos=1)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                self.sent += 1
            else:
                self.failed += 1
            due[i] += PERIOD_S

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def stats_snapshot(table, prefix: str) -> dict:
    snap = {k: 0.0 for k in SUMS}
    hist: dict[str, int] = {}
    kw = {"FilterExpression": Attr("gw").begins_with(prefix)}
    while True:
        resp = table.scan(**kw)
        for item in resp.get("Items", []):
            for k in SUMS:
                snap[k] += float(item.get(k, 0))
            for k, v in item.items():
                if HIST_KEY.match(k):
                    hist[k] = hist.get(k, 0) + int(v)
        if "LastEvaluatedKey" not in resp:
            break
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    snap["hist"] = hist
    return snap


def cw_value(cw, namespace: str, metric: str, dims: dict, t0: datetime, t1: datetime, stat: str = "Sum") -> float:
    kw = {"Namespace": namespace, "MetricName": metric, "StartTime": t0, "EndTime": t1, "Period": 60,
          "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]}
    if stat.startswith("p"):
        points = cw.get_metric_statistics(**kw, ExtendedStatistics=[stat])["Datapoints"]
        return max((p["ExtendedStatistics"][stat] for p in points), default=0.0)
    points = cw.get_metric_statistics(**kw, Statistics=[stat])["Datapoints"]
    if stat == "Sum":
        return sum(p["Sum"] for p in points)
    if stat == "Maximum":
        return max((p["Maximum"] for p in points), default=0.0)
    return sum(p["Average"] for p in points) / len(points) if points else 0.0


def run_level(n: int, minutes: float, warmup: float, per_conn: int, sess, out: dict, tmpl, host: str) -> dict:
    ddb, cw = sess.resource("dynamodb"), sess.client("cloudwatch")
    stats = ddb.Table(out["IngestStatsTableName"])
    prefix = f"lg-{n}-"
    devices = [f"{prefix}{d:05d}" for d in range(n)]
    stop = threading.Event()
    conns = [Connection(f"dc-lg-{n}-{i}", devices[i:i + per_conn], tmpl, host, stop)
             for i in range(0, n, per_conn)]
    deadline = time.time() + 30
    while time.time() < deadline and not all(c.client.is_connected() for c in conns):
        time.sleep(0.2)
    if not all(c.client.is_connected() for c in conns):
        stop.set()
        sys.exit("could not connect all load-generator connections to IoT Core")
    for c in conns:
        c.start()
    print(f"  {n} gateways on {len(conns)} connections; warm-up {warmup:g} min ...", flush=True)
    time.sleep(warmup * 60)
    a, sent_a, t0 = stats_snapshot(stats, prefix), sum(c.sent for c in conns), datetime.now(timezone.utc)
    print(f"  measuring {minutes:g} min ...", flush=True)
    time.sleep(minutes * 60)
    b, sent_b, t1 = stats_snapshot(stats, prefix), sum(c.sent for c in conns), datetime.now(timezone.utc)
    stop.set()
    for c in conns:
        c.join(timeout=5)
        c.close()
    drain_t0, last, still = time.time(), b["msg_count"], time.time()
    while time.time() - drain_t0 < 300:
        time.sleep(5)
        now = stats_snapshot(stats, prefix)["msg_count"]
        if now != last:
            last, still = now, time.time()
        elif time.time() - still >= 15:
            break
    drain_s = max(0.0, still - drain_t0)
    print("  waiting 2 min for CloudWatch metrics ...", flush=True)
    time.sleep(120)

    fn = {"FunctionName": out["DetectorFunctionName"]}
    tables = [out["TelemetryTableName"], out["IngestStatsTableName"]]
    processed = b["msg_count"] - a["msg_count"]
    stamped = b["stamped_count"] - a["stamped_count"]
    hist = {k: b["hist"].get(k, 0) - a["hist"].get(k, 0) for k in set(a["hist"]) | set(b["hist"])}
    span = (t1 - t0).total_seconds()
    mean = lambda f, k=processed: (b[f] - a[f]) / k if k else None  # noqa: E731
    rule = out.get("TelemetryRuleName", "")
    row = {
        "devices": n, "connections": len(conns), "minutes": minutes,
        "sent": sent_b - sent_a, "processed": int(processed),
        "sent_per_s": round((sent_b - sent_a) / span, 2), "processed_per_s": round(processed / span, 2),
        "loss_pct": round(100 * (1 - processed / max(1, sent_b - sent_a)), 2),
        "p50_ms": percentile(hist, 0.50), "p95_ms": percentile(hist, 0.95), "p99_ms": percentile(hist, 0.99),
        "mean_ms": round(mean("latency_sum_ms"), 1) if processed else None,
        "gateway_to_iot_ms": round(mean("to_bridge_sum_ms", stamped), 1) if stamped else None,
        "iot_to_lambda_ms": round(mean("queue_sum_ms", stamped), 1) if stamped else None,
        "handler_ms": round(mean("handler_sum_ms"), 1) if processed else None,
        "lambda_invocations": cw_value(cw, "AWS/Lambda", "Invocations", fn, t0, t1),
        "lambda_errors": cw_value(cw, "AWS/Lambda", "Errors", fn, t0, t1),
        "lambda_throttles": cw_value(cw, "AWS/Lambda", "Throttles", fn, t0, t1),
        "lambda_duration_avg_ms": round(cw_value(cw, "AWS/Lambda", "Duration", fn, t0, t1, "Average"), 1),
        "lambda_duration_p95_ms": round(cw_value(cw, "AWS/Lambda", "Duration", fn, t0, t1, "p95"), 1),
        "lambda_concurrency_max": cw_value(cw, "AWS/Lambda", "ConcurrentExecutions", fn, t0, t1, "Maximum"),
        "ddb_write_throttles": sum(cw_value(cw, "AWS/DynamoDB", "WriteThrottleEvents", {"TableName": t}, t0, t1)
                                   for t in tables),
        "wcu_per_msg": round(sum(cw_value(cw, "AWS/DynamoDB", "ConsumedWriteCapacityUnits", {"TableName": t}, t0, t1)
                                 for t in tables) / max(1, processed), 3),
        "rcu_per_msg": round(cw_value(cw, "AWS/DynamoDB", "ConsumedReadCapacityUnits", {"TableName": tables[0]},
                                      t0, t1) / max(1, processed), 3),
        "iot_rule_failures": sum(cw_value(cw, "AWS/IoT", "Failure", {"RuleName": rule, "ActionType": a_}, t0, t1)
                                 for a_ in ("DynamoDBv2", "Lambda")),
        "backlog_drain_s": round(drain_s, 1),
    }
    return row


def summary(rows: list[dict], limit: int | None) -> str:
    fmt = lambda v: "-" if v is None else ("> 30 s" if v == float("inf") else f"{v:,.0f}")  # noqa: E731
    lines = ["| Gateways | Sent/s | Processed/s | Loss | p50 ms | p95 ms | p99 ms | Gateway→IoT ms | IoT→Lambda ms | "
             "Handler ms | Lambda p95 ms | Peak concurrency | Throttles (Lambda / DynamoDB) | Rule failures |",
             "|" + " --- |" * 14]
    for r in rows:
        lines.append(f"| {r['devices']:,} | {r['sent_per_s']} | {r['processed_per_s']} | {r['loss_pct']} % | "
                     f"{fmt(r['p50_ms'])} | {fmt(r['p95_ms'])} | {fmt(r['p99_ms'])} | {fmt(r['gateway_to_iot_ms'])} | "
                     f"{fmt(r['iot_to_lambda_ms'])} | {fmt(r['handler_ms'])} | {fmt(r['lambda_duration_p95_ms'])} | "
                     f"{r['lambda_concurrency_max']:.0f} | {r['lambda_throttles']:.0f} / {r['ddb_write_throttles']:.0f} | "
                     f"{r['iot_rule_failures']:.0f} |")
    if rows:
        top = max(rows, key=lambda r: r["devices"])
        dur_s = (top["lambda_duration_avg_ms"] or 60) / 1000
        need = 10_000 / PERIOD_S * dur_s
        lines += ["", f"Extrapolation to 10,000 gateways (1,000 messages/s): the detector needs about "
                      f"{math.ceil(need)} concurrent executions at the measured average duration of "
                      f"{top['lambda_duration_avg_ms']:.0f} ms (concurrency = rate x duration)"
                      + (f"; this account allows {limit}." if limit else ".")]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="dev")
    ap.add_argument("--devices", default="50,500,2000")
    ap.add_argument("--minutes", type=float, default=30.0, help="measured minutes per level")
    ap.add_argument("--warmup", type=float, default=3.0, help="minutes before measuring (history, containers)")
    ap.add_argument("--per-connection", type=int, default=50, help="virtual gateways per MQTT connection")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation of the estimated cost")
    args = ap.parse_args()
    if args.stage == "local":
        sys.exit("The load test runs against AWS IoT Core; locally use make latency")
    levels = [int(x) for x in args.devices.split(",")]
    host_file = CERTS / "endpoint.txt"
    if not host_file.exists():
        sys.exit("No device certificate: run make aws-devices first")
    est = estimate_load_test(levels, args.minutes + args.warmup + 1, load_prices())
    msgs = sum(levels) * (args.minutes + args.warmup + 1) * 60 / PERIOD_S
    print(f"Load test {levels} gateways, {args.minutes:g} + {args.warmup:g} min each: about {msgs:,.0f} messages, "
          f"estimated ${est:.2f} at list price (before free tier / credits).")
    if not args.yes and input("Type yes to start: ").strip().lower() != "yes":
        sys.exit("cancelled")

    sess = session(args.stage)
    out = stack_outputs(sess, args.stage)
    events = sess.client("events")
    rule_args = {"Name": out["PlaybookRuleName"], "EventBusName": out["EventBusName"]}
    limit = sess.client("lambda").get_account_settings()["AccountLimit"].get("ConcurrentExecutions")
    print(f"Account Lambda concurrency limit: {limit}. Pausing the playbook rule for the test.", flush=True)
    tmpl = templates()
    host = host_file.read_text().strip()
    rows = []
    RESULTS.mkdir(parents=True, exist_ok=True)
    events.disable_rule(**rule_args)
    try:
        for n in levels:
            print(f"level {n} gateways:", flush=True)
            row = run_level(n, args.minutes, args.warmup, args.per_connection, sess, out, tmpl, host)
            rows.append(row)
            new = not (RESULTS / "e2_runs.csv").exists()
            with open(RESULTS / "e2_runs.csv", "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(row))
                if new:
                    w.writeheader()
                w.writerow(row)
            print(f"  p50 {row['p50_ms']} ms, p95 {row['p95_ms']} ms, processed {row['processed_per_s']}/s, "
                  f"throttles {row['lambda_throttles']:.0f}", flush=True)
    finally:
        events.enable_rule(**rule_args)
        print("Playbook rule re-enabled.")
    text = summary(rows, limit)
    (RESULTS / "e2_summary.md").write_text(text + "\n")
    if rows:
        top = max(rows, key=lambda r: r["devices"])
        usage = {**load_usage(), "source": f"measured on AWS, {top['devices']} gateways",
                 "detector_ms": top["lambda_duration_avg_ms"] or load_usage()["detector_ms"]}
        if top["wcu_per_msg"]:
            usage["telemetry_wru"], usage["stats_wru"] = top["wcu_per_msg"] - 1.0, 1.0
        if top["rcu_per_msg"]:
            usage["history_rru"] = top["rcu_per_msg"]
        (RESULTS / "e2_usage.json").write_text(json.dumps(usage, indent=2))
    print("\n" + text)


if __name__ == "__main__":
    main()
