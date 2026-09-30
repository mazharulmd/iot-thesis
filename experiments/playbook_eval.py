"""Closed-loop playbook evaluation: every fault type x seeds, no AWS needed.

    python -m experiments.playbook_eval [--seeds 11,12,13,14,15]      (make playbook-eval)

For each run: the incident for the injected fault, its final status, time to detect and time to
verified recovery (simulated seconds after the fault started), alerts sent to humans, and any
other incidents. High-risk plans are answered by a simulated operator (default: approve after
120 s). Writes experiments/results/playbooks_summary.md and playbooks_runs.csv.
"""
from __future__ import annotations

import argparse
import csv
import statistics
from datetime import datetime
from pathlib import Path

from detection.evaluate import expected_target
from experiments.closed_loop import fault_scenario, run_closed_loop

FAULTS = ["crah_fan_failure", "sensor_stuck", "sensor_drift", "pump_degradation", "chw_supply_drift",
          "rack_hotspot", "ups_battery_overheat", "pdu_overload"]
OUT = Path(__file__).resolve().parent / "results"


def seconds_after(ts: str | None, start: str, fault_s: float) -> float | None:
    if not ts:
        return None
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return (datetime.fromisoformat(ts.replace("Z", "+00:00")) - t0).total_seconds() - fault_s


def run(seeds: list[int], automation: str = "on", operator: dict | None = None) -> list[dict]:
    rows = []
    for fault in FAULTS:
        for seed in seeds:
            scn = fault_scenario(fault, seed=seed)
            res = run_closed_loop(scn, automation=automation, operator=operator)
            lab = res.labels[0]
            inc = res.incident_for(lab["type"], expected_target(lab))
            others = [i for i in res.incidents if i is not inc and i["status"] != "superseded"]
            rows.append({
                "fault": fault, "seed": seed, "status": inc["status"] if inc else "missed",
                "detect_s": seconds_after(inc["detected_ts"], scn.start_time, lab["start_s"]) if inc else None,
                "verified_s": seconds_after(inc.get("verified_ts"), scn.start_time, lab["start_s"]) if inc else None,
                "correlated": int(inc.get("correlated", 0)) if inc else 0,
                "human_alerts": len(res.alerts), "other_incidents": len(others),
                "commands": len(res.commands),
            })
            print(f"{fault:22s} seed {seed}: {rows[-1]['status']:18s} detect {rows[-1]['detect_s']} "
                  f"verified {rows[-1]['verified_s']} alerts {rows[-1]['human_alerts']}", flush=True)
    return rows


def summary(rows: list[dict]) -> str:
    med = lambda v: f"{statistics.median(v):.0f}" if v else "-"  # noqa: E731
    lines = ["| Fault | Outcome | Median time to detect (s) | Median time to verified recovery (s) | "
             "Related events grouped (median) | Alerts to humans per run (median) | Other incidents |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for fault in FAULTS:
        rs = [r for r in rows if r["fault"] == fault]
        outcome = ", ".join(f"{sum(r['status'] == s for r in rs)}/{len(rs)} {s}"
                            for s in sorted({r["status"] for r in rs}))
        lines.append(f"| {fault} | {outcome} | {med([r['detect_s'] for r in rs if r['detect_s'] is not None])} | "
                     f"{med([r['verified_s'] for r in rs if r['verified_s'] is not None])} | "
                     f"{med([r['correlated'] for r in rs])} | {med([r['human_alerts'] for r in rs])} | "
                     f"{sum(r['other_incidents'] for r in rs)} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", default="11,12,13,14,15")
    ap.add_argument("--automation", default="on", choices=["on", "notify"])
    ap.add_argument("--operator", default="approve", choices=["approve", "reject", "none"])
    ap.add_argument("--operator-delay", type=float, default=120.0)
    args = ap.parse_args()
    op = None if args.operator == "none" else {"decision": args.operator, "delay_s": args.operator_delay}
    rows = run([int(s) for s in args.seeds.split(",")], args.automation, op)
    OUT.mkdir(exist_ok=True)
    suffix = "" if args.automation == "on" else "_notify"
    with open(OUT / f"playbooks_runs{suffix}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    table = summary(rows)
    (OUT / f"playbooks_summary{suffix}.md").write_text(table + "\n")
    print("\n" + table)


if __name__ == "__main__":
    main()
