"""Run a scenario offline and collect gateway messages, a flat table and labels."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .config import HallConfig, ScenarioConfig
from .faults import Fault, SensorLayer, apply_physical_faults
from .model import DataHall


def load_scenario(path: str | Path) -> tuple[ScenarioConfig, dict]:
    """Returns the scenario and its optional plot spec."""
    raw = yaml.safe_load(Path(path).read_text())
    plot = raw.pop("plot", {})
    raw.pop("description", None)
    scn = ScenarioConfig(**raw)
    scn.faults = [Fault(**f) for f in scn.faults]
    return scn, plot


def _iso(start: datetime, t: float) -> str:
    return (start + timedelta(seconds=t)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def flatten(readings: dict) -> dict:
    return {f"{gw}.{a}.{s}": v for gw, assets in readings.items()
            for a, sigs in assets.items() for s, v in sigs.items()}


@dataclass
class RunResult:
    scenario: ScenarioConfig
    messages: list = field(default_factory=list)
    frame: pd.DataFrame | None = None
    labels: dict = field(default_factory=dict)


def run_scenario(scn: ScenarioConfig, cfg: HallConfig | None = None,
                 apply_actions: bool = True, dt_s: float | None = None) -> RunResult:
    cfg = cfg or HallConfig()
    dt = dt_s or cfg.dt_s
    rng = np.random.default_rng(scn.seed)
    hall = DataHall(cfg, rng)
    hall.t = -scn.warmup_s
    hall.init_load(scn.initial_busy_frac)
    sensors = SensorLayer(hall, scn.faults, np.random.default_rng(scn.seed + 10_000))
    start = datetime.fromisoformat(scn.start_time.replace("Z", "+00:00")).astimezone(timezone.utc)

    # Warm-up: reach thermal steady state before t = 0
    while hall.t < 0:
        hall.step(dt)
    hall.t = 0.0

    actions = sorted(scn.actions if apply_actions else [], key=lambda a: a["at_s"])
    applied_actions = []
    seq: dict[str, int] = {}
    messages, rows = [], []
    next_publish = 0.0
    steps = int(round(scn.duration_s / dt))

    for _ in range(steps + 1):
        t = hall.t
        while actions and actions[0]["at_s"] <= t + 1e-9:
            a = actions.pop(0)
            result = hall.apply_command(a["asset"], a["desired"])
            applied_actions.append({"at_s": t, "asset": a["asset"], "desired": a["desired"], "applied": result})

        if t >= next_publish - 1e-9:
            readings = sensors.measure(t)
            ts = _iso(start, t)
            for gw, assets in readings.items():
                seq[gw] = seq.get(gw, 0) + 1
                messages.append({"gw": gw, "ts": ts, "seq": seq[gw], "assets": assets})
            row = {"t_s": round(t, 3), "ts": ts}
            row.update(flatten(readings))
            row["truth.max_t_in"] = round(float(hall.rack_t_in.max()), 3)
            row["truth.it_kw"] = round(float(hall.rack_power.sum()), 3)
            row["truth.q_air_kw"] = round(float(hall.q_air.sum()) / 1000.0, 3)
            active = [f.type for f in scn.faults if t >= f.start_s]
            row["label"] = int(bool(active))
            row["fault_type"] = active[0] if active else ""
            rows.append(row)
            next_publish += cfg.publish_period_s

        apply_physical_faults(hall, scn.faults, t)
        hall.step(dt)

    labels = {
        "scenario": scn.name,
        "seed": scn.seed,
        "duration_s": scn.duration_s,
        "start_time": scn.start_time,
        "publish_period_s": cfg.publish_period_s,
        "faults": [f.label(scn.duration_s) for f in scn.faults],
        "actions": applied_actions,
        "actions_enabled": apply_actions,
    }
    return RunResult(scn, messages, pd.DataFrame(rows), labels)


def save_run(result: RunResult, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "messages.jsonl").open("w") as fh:
        for m in result.messages:
            fh.write(json.dumps(m, separators=(",", ":")) + "\n")
    result.frame.to_csv(out / "telemetry.csv", index=False)
    (out / "labels.json").write_text(json.dumps(result.labels, indent=2))
    return out
