"""Latency probe: where does the time between a gateway message and its detection go?

Runs normal operation at several simulator speeds (5 gateways, one message each per 10
simulated seconds, so speed 1 = 0.5 msg/s, speed 10 = 5 msg/s). For each speed it measures,
over a window after a settling period:

  latency   gateway send -> detector finished (from IngestStats), split into
    to bridge   MQTT delivery until the bridge (IoT rule) receives the message
    bridge      store in DynamoDB + asynchronous Lambda invoke call
    queue       Lambda's asynchronous queue and container dispatch
    handler     inside the handler: history query + detection + publishing
  trend     latency in the first vs second half of the window (growing = cannot keep up)
  drain     how long the Lambda keeps working after the gateways stop (backlog)

    python -m tools.latency [--speeds 1,5,10] [--window 60]      (make latency)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from common.awsenv import session, stack_outputs
from detection.features import CONFIRM, WINDOW

from .prepare_run import prepare, purge_future_telemetry
from .procs import pipeline_running, start, stop, wait_for_line
from .reset_shadows import reset
from .status import SPLIT_SUMS, TIMING_SUMS, gather, percentile
from .warm import warm_up

FIELDS = ("lambda_msgs", "latency_sum_ms", "cold_starts", "stamped_count", *TIMING_SUMS, *SPLIT_SUMS)
OUT = Path("runs/latency")
GATEWAY_MSGS_PER_SIM_S = 5 / 10.0
HISTORY_SIM_S = 10.0 * (WINDOW + CONFIRM)          # messages the detector needs per gateway


def snapshot(stage: str = "local") -> dict:
    rows = gather(stage)
    snap = {f: sum(r[f] for r in rows) for f in FIELDS}
    snap["hist"] = {}
    for r in rows:
        for k, v in r.get("hist", {}).items():
            snap["hist"][k] = snap["hist"].get(k, 0) + v
    snap["t"] = time.time()
    return snap


def window(a: dict, b: dict) -> dict:
    n = b["lambda_msgs"] - a["lambda_msgs"]
    if n <= 0:
        return {"n": 0}
    mean = lambda f, k=n: (b[f] - a[f]) / k  # noqa: E731
    w = {"n": n, "rate": n / (b["t"] - a["t"]), "latency_ms": mean("latency_sum_ms"),
         "handler_ms": mean("handler_sum_ms"), "hist_ms": mean("hist_sum_ms"), "engine_ms": mean("engine_sum_ms"),
         "publish_ms": mean("publish_sum_ms"), "cold_starts": b["cold_starts"] - a["cold_starts"]}
    k = b["stamped_count"] - a["stamped_count"]
    for f in SPLIT_SUMS:
        w[f.replace("_sum_ms", "_ms")] = mean(f, k) if k > 0 else None
    hist = {key: b.get("hist", {}).get(key, 0) - a.get("hist", {}).get(key, 0)
            for key in set(a.get("hist", {})) | set(b.get("hist", {}))}
    for q in (50, 95, 99):
        w[f"p{q}_ms"] = percentile(hist, q / 100)
    return w


def describe(w: dict) -> str:
    if not w.get("n"):
        return "no messages in window"
    parts = ""
    if w.get("queue_ms") is not None:
        parts = (f" = to bridge {w['to_bridge_ms']:.0f} + bridge {w['bridge_ms']:.0f} + queue {w['queue_ms']:.0f}"
                 f" + handler {w['handler_ms']:.0f}")
    cold = f", {w['cold_starts']} cold starts" if w.get("cold_starts") else ""
    p95 = f", p95 ≤ {w['p95_ms']:.0f} ms" if w.get("p95_ms") not in (None, float("inf")) else ""
    return (f"mean {w['latency_ms']:.0f} ms{p95}{parts} (history query {w['hist_ms']:.0f}, "
            f"detection {w['engine_ms']:.1f}) over {w['n']} msgs{cold}")


def wait_drained(stage: str, quiet_s: float = 4, limit_s: float = 300) -> float:
    t0, last, still_since = time.time(), snapshot(stage)["lambda_msgs"], time.time()
    while time.time() - t0 < limit_s:
        time.sleep(1)
        now = snapshot(stage)["lambda_msgs"]
        if now != last:
            last, still_since = now, time.time()
        elif time.time() - still_since >= quiet_s:
            return max(0.0, still_since - t0)
    return limit_s


def main() -> None:
    ap = argparse.ArgumentParser(description="Detector latency probe")
    ap.add_argument("--stage", default="local")
    ap.add_argument("--speeds", default="1,5,10")
    ap.add_argument("--settle", type=float, default=20,
                    help="seconds before measuring at each speed (raised automatically so the detector has "
                         "a full window of history)")
    ap.add_argument("--window", type=float, default=60, help="measurement window per speed (s)")
    args = ap.parse_args()
    if pipeline_running():
        sys.exit("The pipeline is running (make pipeline-up). Stop it first: make pipeline-down")
    speeds = [float(s) for s in args.speeds.split(",")]
    sess = session(args.stage)
    out = stack_outputs(sess, args.stage)
    prepare(args.stage)
    print(f"warm-up: {warm_up(sess, out['DetectorFunctionName'], concurrency=10):.1f} s", flush=True)

    rows = []
    bridge = start("latency-bridge", ["bridge", "--stage", args.stage])
    live = None
    try:
        wait_for_line("latency-bridge", "connected to MQTT", bridge)
        reset()
        for sp in speeds:
            settle = max(args.settle, HISTORY_SIM_S / sp + 5)
            print(f"speed x{sp:g} ({sp * GATEWAY_MSGS_PER_SIM_S:.1f} msg/s): settling {settle:.0f} s, "
                  f"measuring {args.window:.0f} s ...", flush=True)
            live = start("latency-live", ["simulator.live", "--speed", str(sp), "--duration", "0",
                                          "--out", str(OUT / f"speed{sp:g}")])
            wait_for_line("latency-live", "live:", live)
            time.sleep(settle)
            a = snapshot(args.stage)
            time.sleep(args.window / 2)
            m = snapshot(args.stage)
            time.sleep(args.window / 2)
            b = snapshot(args.stage)
            stop(live)
            live = None
            drain = wait_drained(args.stage)
            purge_future_telemetry(sess.resource("dynamodb").Table(out["TelemetryTableName"]))
            whole, first, second = window(a, b), window(a, m), window(m, b)
            rows.append({"speed": sp, "arrival_rate": sp * GATEWAY_MSGS_PER_SIM_S, **whole,
                         "latency_first_half_ms": first.get("latency_ms"),
                         "latency_second_half_ms": second.get("latency_ms"), "drain_s": drain})
            print(f"  {describe(whole)}; drain {drain:.0f} s", flush=True)
    finally:
        stop(live, bridge)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(rows, indent=2))
    head = ("| speed | arrival msg/s | processed msg/s | latency ms (1st half -> 2nd half) | to bridge ms "
            "| bridge ms | queue ms | handler ms | history query ms | detection ms | cold starts | backlog drain s |")
    lines = [head, "|" + " --- |" * 12]
    f = lambda v, d=0: "-" if v is None else f"{v:.{d}f}"  # noqa: E731
    for r in rows:
        if not r.get("n"):
            lines.append(f"| x{r['speed']:g} | {r['arrival_rate']:.1f} | 0 |" + " - |" * 9)
            continue
        lines.append(f"| x{r['speed']:g} | {r['arrival_rate']:.1f} | {r['rate']:.2f} | {r['latency_ms']:.0f} "
                     f"({f(r['latency_first_half_ms'])} -> {f(r['latency_second_half_ms'])}) | "
                     f"{f(r['to_bridge_ms'])} | {f(r['bridge_ms'])} | {f(r['queue_ms'])} | {r['handler_ms']:.0f} | "
                     f"{r['hist_ms']:.0f} | {r['engine_ms']:.1f} | {r['cold_starts']} | {r['drain_s']:.0f} |")
    table = "\n".join(lines)
    (OUT / "summary.md").write_text(table + "\n")
    print("\n" + table + f"\n\nSaved to {OUT}/summary.md")


if __name__ == "__main__":
    main()
