"""Per-run metrics for the experiments (E1, E4), computed the same way for every mode.

All physical metrics use the simulator's true (noise-free) state, recorded at every publish tick,
so a mode is never credited for what its own sensors or detectors believe.

  detected         the injected fault was diagnosed correctly (fault type and target)
  mttd_s           fault start -> first correct diagnosis
  action_s         fault start -> first command for this fault (by its playbook or the simulated operator)
  exceeded         the fault's key value left its normal range at some point
  recovered        the value is back in range and stays there until the end of the run
  mttr_s           fault start -> back in range for good (0 = never left the range: prevented);
                   None when not recovered by the end of the run (right-censored)
  exposure         time-integrated excess over the limit, in the fault's own unit x minutes
  thermal_kmin     hall-wide rack-inlet excess over 27 °C, summed over racks (K·min)
  alerts           messages sent to humans (SNS)
  wrong_actions    incidents that sent commands for a fault that was not injected (any injected
                   fault counts as real, e.g. the faulty sensor in a combined run)
                   (for normal-operation runs every command is a false remediation)

Normal range per fault type (the same limits the playbooks and ASHRAE use):
  crah_fan_failure      every rack inlet in the zone <= 27 °C
  rack_hotspot          the rack's inlet <= 27 °C
  chw_supply_drift      chilled-water supply <= original setpoint + 1 K
  pump_degradation      total chilled-water flow >= 35 L/s and every running pump <= 4.5 mm/s
  ups_battery_overheat  battery <= 35 °C
  pdu_overload          PDU load <= 90 %
  sensor_stuck / drift  the value used for decisions is right: sensor quarantined or within 1 K of truth
"""
from __future__ import annotations

from datetime import datetime

from detection.evaluate import expected_target
from playbooks.catalog import INLET_LIMIT_C, zone_racks

PERIOD_MIN = 10.0 / 60.0
PUMP_MIN_FLOW, PUMP_MAX_VIB = 35.0, 4.5
UPS_MAX_C, PDU_MAX_PCT, SENSOR_TOL_K = 35.0, 90.0, 1.0


def _violation(fault: dict, tv: dict, measured: dict, sp0: float) -> float:
    """How far the key value is outside its normal range (0 = in range) at one tick."""
    ftype, target = fault["type"], fault["target"]
    if ftype == "crah_fan_failure":
        zone = int(target[4:])
        return sum(max(0.0, tv[f"zone{zone}"][r]["t_in"] - INLET_LIMIT_C) for r in zone_racks(zone))
    if ftype == "rack_hotspot":
        gw = f"zone{(int(target[4:]) - 1) // 5 + 1}"
        return max(0.0, tv[gw][target]["t_in"] - INLET_LIMIT_C)
    if ftype == "chw_supply_drift":
        return max(0.0, tv["plant"]["chiller"]["t_sup"] - (sp0 + 1.0))
    if ftype == "pump_degradation":
        pumps = [tv["plant"][p] for p in ("pump1", "pump2")]
        flow = sum(p["flow_lps"] for p in pumps)
        vib = max((p["vib_mms"] for p in pumps if p["flow_lps"] > 5.0), default=0.0)
        return max(0.0, PUMP_MIN_FLOW - flow) + max(0.0, vib - PUMP_MAX_VIB)
    if ftype == "ups_battery_overheat":
        return max(0.0, tv["plant"][target]["t_batt"] - UPS_MAX_C)
    if ftype == "pdu_overload":
        zone = target.replace("zone", "")
        return max(0.0, tv[f"zone{zone}"][f"pdu{zone}"]["load_pct"] - PDU_MAX_PCT)
    if ftype in ("sensor_stuck", "sensor_drift"):
        gw, asset, sig = target.split(".")
        reading = measured.get(gw, {}).get(asset, {})
        if sig in reading.get("quarantined", ()):
            return 0.0
        return max(0.0, abs(reading[sig] - tv[gw][asset][sig]) - SENSOR_TOL_K)
    raise ValueError(f"no normal range defined for {ftype}")


def thermal_kmin(truth: list[dict], start_s: float) -> float:
    total = 0.0
    for tick in truth:
        if tick["t_s"] < start_s:
            continue
        for gw, assets in tick["values"].items():
            for a, v in assets.items():
                if a.startswith("rack"):
                    total += max(0.0, v["t_in"] - INLET_LIMIT_C)
    return round(total * PERIOD_MIN, 3)


def run_metrics(res, fault: dict | None = None) -> dict:
    """Metrics for one closed-loop run. `fault` is the label to score (default: the first non-event)."""
    faults = [lab for lab in res.labels if not lab.get("normal_event")]
    fault = fault or (faults[0] if faults else None)
    start = fault["start_s"] if fault else min((lab["start_s"] for lab in res.labels), default=0.0)
    row = {"thermal_kmin": thermal_kmin(res.truth, start), "alerts": len(res.alerts),
           "dropped": res.dropped, "incidents": len(res.incidents)}
    acted = [i for i in res.incidents if any(s["step"] == "act" for s in i["log"])]
    human = [h for h in res.human_actions if h.get("action") != "none"]
    if fault is None:                                       # normal operation: every command is false
        row.update(false_remediations=len(acted) + len({h["event"] for h in human}),
                   commands=len(res.commands))
        return row

    want = (fault["type"], expected_target(fault))
    real = {(lab["type"], expected_target(lab)) for lab in faults}
    hits = [e for e in res.events if (e["fault_type"], e["target"]) == want and e["t_s"] >= start]
    row["detected"] = bool(hits)
    row["mttd_s"] = hits[0]["t_s"] - start if hits else None
    row["wrong_actions"] = (sum(1 for i in acted if (i["fault_type"], i["target"]) not in real)
                            + len({h["event"] for h in human if tuple(h["event"].split(":")) not in real}))
    inc = next((i for i in res.incidents if (i["fault_type"], i["target"]) == want), None)
    t0 = datetime.fromisoformat(res.truth[0]["wall_start"].replace("Z", "+00:00")).timestamp() if res.truth else 0
    acts = [datetime.fromisoformat(s["at"].replace("Z", "+00:00")).timestamp() - t0
            for s in (inc["log"] if inc else []) if s["step"] == "act"]
    acts += [h["t_s"] for h in human if h["event"] == f"{want[0]}:{want[1]}"]
    row["action_s"] = round(min(acts) - start, 1) if acts else None
    row["incident_status"] = inc["status"] if inc else ("missed" if not hits else "joined")

    measured = {}
    for m in res.messages:
        measured.setdefault(m["t_s"], {})[m["gw"]] = m["assets"]
    sp0 = res.truth[0]["values"]["plant"]["chiller"]["sp"]
    ticks = [t for t in res.truth if t["t_s"] >= start]
    viol = [_violation(fault, t["values"], measured.get(t["t_s"], {}), sp0) for t in ticks]
    bad = [i for i, v in enumerate(viol) if v > 1e-9]
    row["exceeded"] = bool(bad)
    row["exposure"] = round(sum(viol) * PERIOD_MIN, 3)
    if not bad:
        row["recovered"], row["mttr_s"] = True, 0.0
    elif bad[-1] == len(ticks) - 1:
        row["recovered"], row["mttr_s"] = False, None
    else:
        row["recovered"], row["mttr_s"] = True, ticks[bad[-1] + 1]["t_s"] - start
    row["observed_s"] = ticks[-1]["t_s"] - start if ticks else 0.0
    return row
