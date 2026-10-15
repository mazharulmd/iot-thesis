"""Experiment batches (E1, M1 sensitivity, E4, E5) through the offline closed loop.

    python -m experiments.batch --suite e1 [--seeds 20] [--workers 8]      (make e1)
    python -m experiments.batch --suite all                                (make experiments)

Suites
  e1          8 fault types x 3 modes x seeds                        fault response
  m1          alert-only mode with human delays of 5, 10, 20, 30 min  sensitivity of the M1 baseline
  e4_surge    normal operation with a synchronised load swing, 3 modes   false-alarm stress
  e4_sensor   a physical fault while a rack sensor is already faulty, 3 modes
  e4_drop     8 fault types with 5, 10, 20 % of messages lost, M2 and M3
  e5          8 fault types x 3 severity levels x 3 modes x 10 seeds    is the ranking robust to severity?

Modes
  M1  alert only: static limits (D0); a human reads the alert and carries out the playbook by hand
  M2  static limits (D0) + automated playbooks
  M3  ML hybrid (D2h) + automated playbooks (the proposed framework)

The human's response time is log-normal with a median of 10 min (sigma 0.5: 90 % between 4.4 and
22.8 min), drawn once per seed so all modes of a seed face the same person (paired design). The
same delay is used for approving high-risk plans in M2 and M3.

Rows are appended to experiments/results/runs.csv as runs finish; an interrupted batch resumes
where it stopped. Seeds 1001+ are not used by training (101-108), thresholds (201-208) or the
detector evaluation (11-15).
"""
from __future__ import annotations

import argparse
import csv
import math
import multiprocessing as mp
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "results" / "runs.csv"
FAULTS = ["crah_fan_failure", "sensor_stuck", "sensor_drift", "pump_degradation", "chw_supply_drift",
          "rack_hotspot", "ups_battery_overheat", "pdu_overload"]
MODES = {"M1": {"detector": "d0", "automation": "notify"},
         "M2": {"detector": "d0", "automation": "on"},
         "M3": {"detector": "d2h", "automation": "on"}}
FAULT_AT, AFTER = 600.0, 2700.0                 # fault 10 min in, 45 min observed after it
HUMAN_MEDIAN_S, HUMAN_SIGMA = 600.0, 0.5
SENSOR_COMBOS = {                               # physical fault + a sensor that failed 5 min earlier
    "crah2_with_stuck_rack07": ("crah_fan_failure", "sensor_stuck"),
    "chw_with_drifting_rack12": ("chw_supply_drift", "sensor_drift"),
}
# E5 severity levels, mildest (L1) to harshest (L3). The level with no changes is the E1 fault, so
# E5 also re-runs E1 for seeds 1001-1010 (a reproducibility check). Changes go to the fault, except
# initial_busy_frac, which sets how many racks run jobs at the start (the heat load a CRAH failure
# has to cope with): a CRAH failure is on/off, so its severity is the load it fails under.
E5_LEVELS = {
    "crah_fan_failure":     [("L1", "40 % of racks busy", {"initial_busy_frac": 0.4}),
                             ("L2", "80 % of racks busy (E1)", {}),
                             ("L3", "all racks busy", {"initial_busy_frac": 1.0})],
    "rack_hotspot":         [("L1", "50 % local airflow loss", {"severity": 0.5}),
                             ("L2", "65 % local airflow loss (E1)", {}),
                             ("L3", "80 % local airflow loss", {"severity": 0.8})],
    "chw_supply_drift":     [("L1", "+4 K over 10 min", {"severity": 4.0}),
                             ("L2", "+7 K over 10 min (E1)", {}),
                             ("L3", "+10 K over 10 min", {"severity": 10.0})],
    "pump_degradation":     [("L1", "40 % health lost over 30 min", {"severity": 0.4}),
                             ("L2", "60 % health lost over 30 min (E1)", {}),
                             ("L3", "80 % health lost over 30 min", {"severity": 0.8})],
    "sensor_stuck":         [("L1", "frozen at the true value (E1)", {}),
                             ("L2", "frozen 3 K below the true value", {"offset": -3.0}),
                             ("L3", "frozen 6 K below the true value", {"offset": -6.0})],
    "sensor_drift":         [("L1", "0.25 K/min", {"severity": 0.25}),
                             ("L2", "0.5 K/min (E1)", {}),
                             ("L3", "1 K/min", {"severity": 1.0})],
    "ups_battery_overheat": [("L1", "0.5 K/min at half load", {"severity": 0.5}),
                             ("L2", "1 K/min at half load (E1)", {}),
                             ("L3", "2 K/min at half load", {"severity": 2.0})],
    "pdu_overload":         [("L1", "racks at 106 % of rating", {"severity": 1.06}),
                             ("L2", "racks at 112 % of rating (E1)", {}),
                             ("L3", "racks at 118 % of rating", {"severity": 1.18})],
}
FIELDS = ["suite", "mode", "fault", "seed", "param", "human_delay_s", "detected", "mttd_s", "action_s",
          "incident_status", "exceeded", "recovered", "mttr_s", "exposure", "thermal_kmin", "alerts",
          "wrong_actions", "false_remediations", "commands", "incidents", "dropped", "observed_s",
          "runtime_s", "error"]


def human_delay(seed: int, median_s: float = HUMAN_MEDIAN_S) -> float:
    z = np.random.default_rng(seed + 50_000).standard_normal()
    return round(median_s * math.exp(HUMAN_SIGMA * z), 1)


def specs(suite: str, seeds: int) -> list[dict]:
    first = 1001
    out = []
    if suite == "e1":
        for f in FAULTS:
            for m in MODES:
                out += [{"suite": "e1", "mode": m, "fault": f, "seed": s, "param": ""} for s in range(first, first + seeds)]
    elif suite == "m1":
        for delay_min in (5, 10, 20, 30):
            for f in FAULTS:
                out += [{"suite": "m1", "mode": "M1", "fault": f, "seed": s, "param": delay_min}
                        for s in range(first, first + min(seeds, 10))]
    elif suite == "e4_surge":
        for m in MODES:
            out += [{"suite": "e4_surge", "mode": m, "fault": "load_surge", "seed": s, "param": ""}
                    for s in range(first, first + seeds)]
    elif suite == "e4_sensor":
        for combo in SENSOR_COMBOS:
            for m in MODES:
                out += [{"suite": "e4_sensor", "mode": m, "fault": combo, "seed": s, "param": ""}
                        for s in range(first, first + min(seeds, 10))]
    elif suite == "e4_drop":
        for rate in (0.05, 0.10, 0.20):
            for f in FAULTS:
                for m in ("M2", "M3"):
                    out += [{"suite": "e4_drop", "mode": m, "fault": f, "seed": s, "param": rate}
                            for s in range(first, first + min(seeds, 10))]
    elif suite == "e5":
        for f in FAULTS:
            for level, _, _ in E5_LEVELS[f]:
                for m in MODES:
                    out += [{"suite": "e5", "mode": m, "fault": f, "seed": s, "param": level}
                            for s in range(first, first + min(seeds, 10))]
    else:
        raise ValueError(f"unknown suite {suite}")
    return out


def apply_level(scn, fault: str, level: str):
    """Set an E5 severity level on a fault scenario (in place) and return it."""
    changes = next(c for lv, _, c in E5_LEVELS[fault] if lv == level)
    for key, value in changes.items():
        if key == "initial_busy_frac":
            scn.initial_busy_frac = value
        else:
            for f in scn.faults:
                setattr(f, key, value)
    scn.name = f"{fault}_{level}"
    return scn


def scenario(spec: dict):
    from experiments.closed_loop import fault_scenario
    from simulator.config import ScenarioConfig
    from simulator.faults import Fault

    if spec["fault"] == "load_surge":
        zone = f"zone{spec['seed'] % 4 + 1}"
        return ScenarioConfig(name="load_surge", duration_s=FAULT_AT + AFTER, seed=spec["seed"],
                              faults=[Fault("load_surge", zone, FAULT_AT, 1.0, duration_s=1800.0)])
    if spec["fault"] in SENSOR_COMBOS:
        physical, sensor = SENSOR_COMBOS[spec["fault"]]
        scn = fault_scenario(physical, FAULT_AT, AFTER, spec["seed"])
        extra = fault_scenario(sensor, FAULT_AT - 300.0, AFTER, spec["seed"]).faults
        if physical == "chw_supply_drift":
            for f in extra:
                f.target = "zone3.rack12.t_in"
        scn.faults = scn.faults + extra
        scn.name = spec["fault"]
        return scn
    scn = fault_scenario(spec["fault"], FAULT_AT, AFTER, spec["seed"])
    if spec["suite"] == "e5":
        apply_level(scn, spec["fault"], spec["param"])
    return scn


def run_one(spec: dict) -> dict:
    from experiments.closed_loop import run_closed_loop
    from experiments.metrics import run_metrics

    t0 = time.time()
    row = {k: spec.get(k, "") for k in ("suite", "mode", "fault", "seed", "param")}
    try:
        median = (spec["param"] * 60.0) if spec["suite"] == "m1" else HUMAN_MEDIAN_S
        delay = human_delay(spec["seed"], median)
        mode = MODES[spec["mode"]]
        scn = scenario(spec)
        res = run_closed_loop(scn, detector=mode["detector"], automation=mode["automation"],
                              operator={"decision": "approve", "delay_s": delay},
                              human={"delay_s": delay, "stage_gap_s": 120.0} if mode["automation"] == "notify" else None,
                              drop_rate=float(spec["param"]) if spec["suite"] == "e4_drop" else 0.0)
        row["human_delay_s"] = delay
        row.update(run_metrics(res))
    except Exception:  # noqa: BLE001 - one failed run must not stop a batch
        row["error"] = traceback.format_exc(limit=3).replace("\n", " | ")[-500:]
    row["runtime_s"] = round(time.time() - t0, 1)
    return row


def _key(row: dict) -> tuple:
    return (row["suite"], row["mode"], row["fault"], str(row["seed"]), str(row["param"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="e1", help="e1, m1, e4_surge, e4_sensor, e4_drop, e4, e5 or all (comma-separated)")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    names = []
    for s in args.suite.split(","):
        names += {"all": ["e1", "m1", "e4_surge", "e4_sensor", "e4_drop", "e5"],
                  "e4": ["e4_surge", "e4_sensor", "e4_drop"]}.get(s, [s])
    todo = [sp for n in names for sp in specs(n, args.seeds)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        with open(args.out) as fh:
            done = {_key(r) for r in csv.DictReader(fh) if not r.get("error")}
    todo = [sp for sp in todo if _key(sp) not in done]
    print(f"{len(todo)} runs to do ({len(done)} already in {args.out}), {args.workers} workers; "
          f"about {len(todo) * 12 / args.workers / 60:.0f} min", flush=True)
    if not todo:
        return
    new_file = not args.out.exists()
    t0 = time.time()
    errors = 0
    with open(args.out, "a", newline="") as fh, mp.get_context("fork").Pool(args.workers) as pool:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        for n, row in enumerate(pool.imap_unordered(run_one, todo, chunksize=1), 1):
            w.writerow(row)
            fh.flush()
            errors += bool(row.get("error"))
            status = "ERROR" if row.get("error") else f"{row.get('incident_status', row.get('false_remediations'))}"
            if n % 10 == 0 or row.get("error") or n == len(todo):
                rate = (time.time() - t0) / n
                print(f"  {n}/{len(todo)}  {row['suite']} {row['mode']} {row['fault']} {row['seed']} "
                      f"{row['param']}: {status}   ~{rate * (len(todo) - n) / 60:.0f} min left", flush=True)
    print(f"done in {(time.time() - t0) / 60:.1f} min -> {args.out}{' (' + str(errors) + ' errors)' if errors else ''}")
    sys.exit(0)


if __name__ == "__main__":
    main()
