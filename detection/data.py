"""Generate and cache simulator runs used for training and evaluation."""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from simulator.config import ScenarioConfig
from simulator.runner import load_scenario, run_scenario

from .features import asset_series, windows

CACHE = Path(__file__).resolve().parent / "data"
SCENARIOS = Path(__file__).resolve().parents[1] / "simulator" / "scenarios"


def _normal_run(args) -> list[dict]:
    seed, hours = args
    path = CACHE / f"normal-s{seed}-{hours:g}h.jsonl.gz"
    if path.exists():
        with gzip.open(path, "rt") as fh:
            return [json.loads(line) for line in fh]
    msgs = run_scenario(ScenarioConfig(name="normal", duration_s=hours * 3600, seed=seed)).messages
    CACHE.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        for m in msgs:
            fh.write(json.dumps(m, separators=(",", ":")) + "\n")
    return msgs


def normal_runs(seeds: list[int], hours: float, workers: int = 4) -> list[list[dict]]:
    with Pool(workers) as pool:
        return pool.map(_normal_run, [(s, hours) for s in seeds])


def _fault_run(args):
    name, seed = args
    scn, _ = load_scenario(SCENARIOS / f"{name}.yaml")
    scn.seed = seed
    res = run_scenario(scn, apply_actions=False)
    return name, seed, res.messages, res.labels


def fault_runs(names: list[str], seeds: list[int], workers: int = 4):
    with Pool(workers) as pool:
        return pool.map(_fault_run, [(n, s) for n in names for s in seeds])


def by_gateway(msgs: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for m in msgs:
        out[m["gw"]].append(m)
    for gw in out:
        out[gw].sort(key=lambda m: m["seq"])
    return out


def collect(runs: list[list[dict]]) -> dict[str, dict]:
    """kind -> {"base": (M, n) signal rows, "win": (P, WINDOW, n) complete windows}."""
    base, win = defaultdict(list), defaultdict(list)
    for msgs in runs:
        for gw_msgs in by_gateway(msgs).values():
            for _, (kind, arr) in asset_series(gw_msgs).items():
                base[kind].append(arr[~np.isnan(arr).any(axis=1)])
                w = windows(arr)
                win[kind].append(w[~np.isnan(w).any(axis=(1, 2))])
    return {k: {"base": np.concatenate(base[k]), "win": np.concatenate(win[k])} for k in base}
