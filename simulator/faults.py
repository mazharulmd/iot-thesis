"""Fault injection.

Physical faults change the model's state; sensor faults change only what the
gateways report. Ground truth is written to labels.json and never published.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.catalog import FAULT_CATALOG  # (risk tier, playbook) per fault type

from .model import DataHall

SENSOR_FAULTS = {"sensor_stuck", "sensor_drift"}
# Normal operating events injected for robustness tests (E4). They are not faults: the expected
# response is no automated action.
NORMAL_EVENTS = {"load_surge"}


@dataclass
class Fault:
    type: str
    target: str
    start_s: float
    severity: float = 1.0
    ramp_s: float = 0.0          # 0 = step change
    duration_s: float = 0.0      # 0 = until the end of the run (used by normal events)

    def __post_init__(self) -> None:
        if self.type not in FAULT_CATALOG and self.type not in NORMAL_EVENTS:
            raise ValueError(f"unknown fault type {self.type!r}; choose from {sorted(FAULT_CATALOG)}")

    @property
    def is_normal_event(self) -> bool:
        return self.type in NORMAL_EVENTS

    def active(self, t: float) -> bool:
        return t >= self.start_s and (self.duration_s <= 0 or t < self.start_s + self.duration_s)

    def progress(self, t: float) -> float:
        if t < self.start_s:
            return 0.0
        if self.ramp_s <= 0:
            return 1.0
        return min(1.0, (t - self.start_s) / self.ramp_s)

    @property
    def is_sensor_fault(self) -> bool:
        return self.type in SENSOR_FAULTS

    def label(self, duration_s: float) -> dict:
        risk, playbook = FAULT_CATALOG.get(self.type, ("none", None))
        return {
            "type": self.type,
            "target": self.target,
            "start_s": self.start_s,
            "end_s": duration_s,
            "severity": self.severity,
            "ramp_s": self.ramp_s,
            "duration_s": self.duration_s,
            "normal_event": self.is_normal_event,
            "risk": risk,
            "expected_playbook": playbook,
        }


def apply_physical_faults(hall: DataHall, faults: list[Fault], t: float) -> None:
    c = hall.cfg
    for f in faults:
        if f.type == "load_surge":
            # a synchronised load swing in one zone: all racks idle for the first half of the event,
            # then all start a busy job at once (a large training job launching); then back to normal
            z = int(f.target.replace("zone", "")) - 1
            idx = np.arange(z * c.racks_per_zone, (z + 1) * c.racks_per_zone)
            if not f.active(t):
                if t >= f.start_s:
                    hall.rack_force_frac[idx] = np.nan
                continue
            half = f.duration_s / 2 if f.duration_s > 0 else 600.0
            busy = t >= f.start_s + half
            hall.rack_force_frac[idx] = (c.rack_busy_frac * f.severity) if busy else c.rack_idle_frac
            continue
        if f.is_sensor_fault or t < f.start_s:
            continue
        p = f.progress(t)
        if f.type == "crah_fan_failure":
            crah = hall.standby if f.target == hall.standby.name else hall._crah(f.target)
            crah.status = "failed"
        elif f.type == "pump_degradation":
            pump = next(x for x in hall.pumps if x.name == f.target)
            pump.health = 1.0 - f.severity * p            # severity = fraction of health lost
        elif f.type == "chw_supply_drift":
            hall.chw_drift = f.severity * p                # severity = kelvin of drift
        elif f.type == "rack_hotspot":
            hall.rack_hotspot[int(f.target[4:]) - 1] = f.severity * p   # local airflow loss
        elif f.type == "ups_battery_overheat":
            ups = next(u for u in hall.ups if u.name == f.target)
            ups.fault_heat_k_per_min = f.severity * p      # severity = K/min at half load
        elif f.type == "pdu_overload":
            z = int(f.target.replace("zone", "")) - 1
            idx = np.arange(z * c.racks_per_zone, (z + 1) * c.racks_per_zone)
            hall.rack_force_frac[idx] = f.severity         # severity = fraction of rack rating


# ---------------------------------------------------------------- sensor layer
NOISE_ABS = {"t_": "noise_temp_c", "vib_mms": "noise_vib_mm_s"}
NOISE_REL = {"p_kw": "noise_power_rel", "load_kw": "noise_power_rel", "i_a": "noise_current_rel",
             "flow_lps": "noise_flow_rel", "dp_kpa": "noise_flow_rel", "load_pct": "noise_power_rel"}
NO_NOISE = {"fan_pct", "sp", "zone", "status", "assist", "v_batt"}


class SensorLayer:
    """Adds measurement noise and applies sensor faults."""

    def __init__(self, hall: DataHall, faults: list[Fault], rng: np.random.Generator):
        self.hall = hall
        self.cfg = hall.cfg
        self.rng = rng
        self.faults = [f for f in faults if f.is_sensor_fault]
        self.stuck_value: dict[str, float] = {}

    def _noise(self, signal: str, value: float) -> float:
        c = self.cfg
        if signal in NO_NOISE:
            return value
        if signal in NOISE_REL:
            return value * (1.0 + self.rng.normal(0, getattr(c, NOISE_REL[signal])))
        for prefix, attr in NOISE_ABS.items():
            if signal.startswith(prefix) or signal == prefix:
                return value + self.rng.normal(0, getattr(c, attr))
        return value

    def measure(self, t: float) -> dict:
        true = self.hall.true_readings()
        out: dict = {}
        for gw, assets in true.items():
            out[gw] = {}
            for asset, signals in assets.items():
                out[gw][asset] = {}
                for sig, val in signals.items():
                    if isinstance(val, str):
                        out[gw][asset][sig] = val
                        continue
                    v = self._noise(sig, float(val))
                    v = self._apply_sensor_faults(f"{gw}.{asset}.{sig}", v, t)
                    out[gw][asset][sig] = int(v) if sig == "zone" else round(v, 2)
        for flagged in sorted(self.hall.flagged_sensors):      # gateway marks quarantined sensors
            asset, sig = flagged.split(".", 1)
            for gw in out:
                if asset in out[gw]:
                    out[gw][asset].setdefault("quarantined", []).append(sig)
        return out

    def _apply_sensor_faults(self, key: str, value: float, t: float) -> float:
        for f in self.faults:
            if f.target != key or t < f.start_s:
                continue
            if f.type == "sensor_stuck":
                value = self.stuck_value.setdefault(key, value)
            elif f.type == "sensor_drift":
                minutes = (t - f.start_s) / 60.0
                value += min(15.0, f.severity * minutes)   # severity = K/min, capped at +15
        return value
