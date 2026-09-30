"""Command-line entry point.

Examples:
    python -m simulator.run simulator/scenarios/crah_fan_failure.yaml
    python -m simulator.run simulator/scenarios/crah_fan_failure.yaml --no-actions
    python -m simulator.run --all
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from .plots import plot_run
from .runner import load_scenario, run_scenario, save_run

SCENARIO_DIR = Path(__file__).parent / "scenarios"


def run_one(path: Path, out_root: Path, apply_actions: bool, duration: float | None) -> None:
    scn, plot_spec = load_scenario(path)
    if duration:
        scn.duration_s = duration
    t0 = time.time()
    result = run_scenario(scn, apply_actions=apply_actions)
    suffix = "" if apply_actions else "_no_actions"
    out = save_run(result, out_root / f"{scn.name}{suffix}")
    plot_run(result.frame, result.labels, plot_spec, out / "plot.png")
    print(f"{scn.name + suffix:34s} {len(result.messages):6d} messages  "
          f"{time.time() - t0:5.1f}s  -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run data hall scenarios offline.")
    ap.add_argument("scenarios", nargs="*", type=Path, help="scenario YAML files")
    ap.add_argument("--all", action="store_true", help="run every scenario in simulator/scenarios")
    ap.add_argument("--no-actions", action="store_true", help="ignore scripted remediation actions")
    ap.add_argument("--both", action="store_true", help="run each scenario with and without actions")
    ap.add_argument("--duration", type=float, help="override duration in seconds")
    ap.add_argument("--out", type=Path, default=Path("runs"), help="output folder (default: runs)")
    args = ap.parse_args()

    paths = sorted(p for p in SCENARIO_DIR.glob("*.yaml") if not p.name.startswith("e2e_")) if args.all else args.scenarios
    if not paths:
        ap.error("give scenario files or --all")
    for p in paths:
        modes = [True, False] if args.both else [not args.no_actions]
        for mode in modes:
            run_one(p, args.out, mode, args.duration)


if __name__ == "__main__":
    main()
