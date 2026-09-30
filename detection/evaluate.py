"""Offline evaluation of D0 / D1 / D2 on simulated faults and normal operation (RQ2).

    python -m detection.evaluate                  # 8 faults x 5 seeds, 4 x 6 h normal

For each fault run (no remediation) and detector:
  detected   an event with the right fault type AND the right target after fault start
  mttd_s     seconds from fault start to that event
  wrong      other automated-playbook events after fault start (misdiagnosis)
Normal runs give false alarms per 24 h, split into automated vs notify-only.
Seeds are disjoint from the training and validation seeds.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .data import by_gateway, fault_runs, normal_runs
from .engine import DetectionEngine
from .models import Bundle

RESULTS = Path(__file__).resolve().parent / "results"
FAULTS = ["crah_fan_failure", "sensor_stuck", "sensor_drift", "pump_degradation",
          "chw_supply_drift", "rack_hotspot", "ups_battery_overheat", "pdu_overload"]
PERIOD_S = 10.0


def expected_target(label: dict) -> str:
    target = label["target"]
    if label["type"] == "pdu_overload":
        return "pdu" + target.replace("zone", "")
    if "." in target:                                   # sensor fault: zone2.rack07.t_in
        return target.split(".")[1]
    return target


def run_events(engine: DetectionEngine, msgs: list[dict]) -> list[dict]:
    events = []
    for gw_msgs in by_gateway(msgs).values():
        events.extend(engine.process_series(gw_msgs))
    for e in events:
        e["t_s"] = (e["seq"] - 1) * PERIOD_S
    return sorted(events, key=lambda e: e["t_s"])


def evaluate_fault(engine, name, seed, msgs, labels) -> dict:
    label = labels["faults"][0]
    start, want = label["start_s"], (label["type"], expected_target(label))
    events = run_events(engine, msgs)
    after = [e for e in events if e["t_s"] >= start]
    hits = [e for e in after if (e["fault_type"], e["target"]) == want]
    wrong = [e for e in after if (e["fault_type"], e["target"]) != want and e["playbook"] != "notify_only"]
    return {
        "detector": engine.detector, "fault": name, "seed": seed,
        "detected": bool(hits), "mttd_s": hits[0]["t_s"] - start if hits else np.nan,
        "first_event": f"{after[0]['fault_type']}:{after[0]['target']}" if after else "",
        "wrong_automated": len(wrong), "notify_after": sum(e["playbook"] == "notify_only" for e in after),
        "false_before_fault": len([e for e in events if e["t_s"] < start]),
    }


def evaluate_normal(engine, seed, msgs) -> dict:
    events = run_events(engine, msgs)
    hours = (max(m["seq"] for m in msgs) * PERIOD_S) / 3600.0
    automated = [e for e in events if e["playbook"] != "notify_only"]
    return {"detector": engine.detector, "seed": seed, "hours": hours, "events": len(events),
            "automated": len(automated), "notify_only": len(events) - len(automated),
            "types": json.dumps(pd.Series([e["fault_type"] for e in events]).value_counts().to_dict())}


def summarise(faults: pd.DataFrame, normal: pd.DataFrame) -> str:
    dets = list(dict.fromkeys(faults.detector))
    seeds = faults.groupby(["fault", "detector"]).size().max()
    lines = [f"## Detection per fault ({seeds} seeds each): detected / median MTTD in seconds", "",
             "| Fault | " + " | ".join(d.upper() for d in dets) + " |",
             "| --- |" + " --- |" * len(dets)]
    for name in FAULTS:
        cells = []
        for d in dets:
            sub = faults[(faults.fault == name) & (faults.detector == d)]
            mttd = sub.mttd_s.median()
            cells.append(f"{int(sub.detected.sum())}/{len(sub)} · " + ("–" if np.isnan(mttd) else f"{mttd:.0f} s"))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Overall", "", "| Detector | Faults detected | Median MTTD (s) | Wrong automated events | "
              "False alarms / 24 h (automated) | False alarms / 24 h (notify-only) |", "| --- | --- | --- | --- | --- | --- |"]
    for d in dets:
        f = faults[faults.detector == d]
        n = normal[normal.detector == d]
        per_day = 24.0 / n.hours.sum()
        lines.append(f"| {d.upper()} | {int(f.detected.sum())}/{len(f)} | {f.mttd_s.median():.0f} | "
                     f"{int(f.wrong_automated.sum())} | {n.automated.sum() * per_day:.2f} | "
                     f"{n.notify_only.sum() * per_day:.2f} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline evaluation of the detectors")
    ap.add_argument("--seeds", type=int, default=5, help="seeds per fault scenario")
    ap.add_argument("--normal-seeds", type=int, default=4)
    ap.add_argument("--normal-hours", type=float, default=6.0)
    ap.add_argument("--detectors", default="d0,d1,d2,d1h,d2h")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--bundle", type=Path, default=None, help="bundle folder (default: detection/models)")
    ap.add_argument("--out", type=Path, default=RESULTS, help="results folder")
    args = ap.parse_args()
    t0 = time.time()
    bundle = Bundle.load(args.bundle) if args.bundle else Bundle.load()
    engines = [DetectionEngine(bundle, d) for d in args.detectors.split(",")]

    print(f"simulating {len(FAULTS)} faults x {args.seeds} seeds and "
          f"{args.normal_seeds} x {args.normal_hours:g} h normal ...", flush=True)
    fruns = fault_runs(FAULTS, list(range(11, 11 + args.seeds)), args.workers)
    nruns = normal_runs(list(range(301, 301 + args.normal_seeds)), args.normal_hours, args.workers)

    frows, nrows = [], []
    for engine in engines:
        print(f"scoring {engine.detector} ...", flush=True)
        frows += [evaluate_fault(engine, n, s, m, lab) for n, s, m, lab in fruns]
        nrows += [evaluate_normal(engine, s, m) for s, m in zip(range(301, 301 + args.normal_seeds), nruns)]
    faults, normal = pd.DataFrame(frows), pd.DataFrame(nrows)

    args.out.mkdir(parents=True, exist_ok=True)
    faults.to_csv(args.out / "offline_faults.csv", index=False)
    normal.to_csv(args.out / "offline_normal.csv", index=False)
    summary = summarise(faults, normal)
    (args.out / "offline_summary.md").write_text(summary + "\n")
    print("\n" + summary)
    print(f"\nwrote {args.out}/offline_*.csv and offline_summary.md in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
