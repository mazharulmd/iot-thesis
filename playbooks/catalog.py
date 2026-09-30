"""Remediation playbooks as data.

A playbook turns an anomaly event (plus the latest telemetry of every gateway) into a plan:

    {"playbook", "risk", "target", "commanded": [assets], "affected": [assets],
     "stages": [{"name", "commands": {asset: desired}, "checks": [check], "stable": n, "timeout_msgs": n,
                 "rollback": {asset: desired}, "rollback_note": "why"}],
     "ticket": "text for the maintenance ticket"}

A stage's commands are sent as device-shadow `desired` state; the stage is verified when every
check holds on the last `stable` telemetry messages sent after the commands, and fails when
`timeout_msgs` messages arrive without that. A failed stage sends its `rollback` commands, which
return the equipment to the last configuration that was verified (or to its state before the
playbook); an empty rollback means holding the new state is safer than undoing it, and
`rollback_note` says why. Checks are plain comparisons on telemetry:

    {"gw": "zone2", "asset": "rack07", "signal": "t_in", "op": "le", "value": 27.0}

Keeping playbooks as data makes every automated action explainable and lets one state machine
(playbooks/state_machine.py) run all of them. The same code runs in the Lambda and offline.
"""
from __future__ import annotations

from common.catalog import FAULT_CATALOG
from common.topology import RACKS_PER_ZONE, gateway_of

INLET_LIMIT_C = 27.0          # ASHRAE recommended maximum rack inlet temperature
STABLE = 3                    # consecutive messages (30 s) a check must hold
TIMEOUT_MSGS = 60             # 10 simulated minutes per stage
N_ZONES = 4
STANDBY_CRAH = "crah5"


class PlanError(Exception):
    """The playbook cannot run safely in the current state (goes to a human)."""


def check(asset: str, signal: str, op: str, value) -> dict:
    return {"gw": gateway_of(asset), "asset": asset, "signal": signal, "op": op, "value": value}


def zone_of(asset: str) -> int:
    gw = gateway_of(asset)
    if not gw.startswith("zone"):
        raise PlanError(f"{asset} is not in a zone")
    return int(gw[4:])


def zone_racks(zone: int) -> list[str]:
    first = (zone - 1) * RACKS_PER_ZONE + 1
    return [f"rack{i:02d}" for i in range(first, first + RACKS_PER_ZONE)]


def reading(snapshot: dict, asset: str, signal: str):
    msg = snapshot.get(gateway_of(asset))
    if not msg:
        raise PlanError(f"no recent telemetry from {gateway_of(asset)}")
    try:
        return msg["assets"][asset][signal]
    except KeyError:
        raise PlanError(f"{asset}.{signal} missing from telemetry") from None


def stage(name: str, commands: dict, checks: list[dict], stable: int = STABLE,
          timeout_msgs: int = TIMEOUT_MSGS, rollback: dict | None = None, rollback_note: str = "") -> dict:
    return {"name": name, "commands": commands, "checks": checks, "stable": stable, "timeout_msgs": timeout_msgs,
            "rollback": rollback or {}, "rollback_note": rollback_note}


# ---------------------------------------------------------------------------------------- playbooks
def cooling_unit_failover(event: dict, snap: dict) -> dict:
    """Failed CRAH: boost the neighbouring zones' units, start the standby unit in the zone, then
    hand the neighbours and the standby to automatic control once the standby carries the zone
    (a standby at fixed speed would over-cool the zone and spill cold air into its neighbours)."""
    target = event["target"]
    zone = zone_of(target)
    if reading(snap, target, "status") == "on" and reading(snap, target, "fan_pct") > 0:
        raise PlanError(f"{target} is running again; nothing to fail over")
    neighbours = [f"crah{z}" for z in (zone - 1, zone + 1) if 1 <= z <= N_ZONES]
    neighbours = [c for c in neighbours if reading(snap, c, "status") == "on"]
    standby_free = reading(snap, STANDBY_CRAH, "status") == "off"
    if not neighbours and not standby_free:
        raise PlanError("no neighbouring or standby cooling available")
    racks = zone_racks(zone)
    cool = [check(r, "t_in", "le", INLET_LIMIT_C) for r in racks]
    commands = {c: {"fan_pct": 100} for c in neighbours}
    checks = list(cool)
    if standby_free:
        commands[STANDBY_CRAH] = {"status": "on", "zone": zone, "fan_pct": 90}
        checks += [check(STANDBY_CRAH, "status", "eq", "on"), check(STANDBY_CRAH, "zone", "eq", zone)]
    stages = [stage("boost neighbours and start standby" if standby_free else "boost neighbours", commands, checks,
                    rollback_note="hold: extra cooling cannot make the zone hotter; a human takes over")]
    if standby_free:
        auto = {c: {"fan_mode": "auto", "fan_pct": None} for c in [*neighbours, STANDBY_CRAH]}
        boost = {c: {"fan_pct": 100} for c in neighbours} | {STANDBY_CRAH: {"fan_pct": 90}}
        stages.append(stage("hand neighbours and standby to automatic control", auto,
                            cool + [check(STANDBY_CRAH, "status", "eq", "on")], stable=6, timeout_msgs=30,
                            rollback=boost, rollback_note="back to the verified boost configuration"))
    return {"commanded": sorted(commands), "affected": racks + [f"pdu{zone}", "chiller"], "stages": stages,
            "ticket": f"Repair {target} (zone {zone}); standby {'in service' if standby_free else 'unavailable'}."}


def sensor_quarantine(event: dict, snap: dict) -> dict:
    """Faulty sensor: flag it so the gateway marks it quarantined and decisions ignore it."""
    target = event["target"]
    signal = (event.get("evidence") or {}).get("signal", "t_in")
    reading(snap, target, signal)                                  # the sensor must exist
    return {"commanded": [target], "affected": [],
            "stages": [stage(f"quarantine {target}.{signal}", {target: {"sensor_flag": signal}},
                             [check(target, "quarantined", "contains", signal)], stable=1, timeout_msgs=12,
                             rollback={target: {"sensor_flag": None}}, rollback_note="clear the flag")],
            "ticket": f"Replace or recalibrate sensor {target}.{signal}."}


def pump_switchover(event: dict, snap: dict) -> dict:
    """Degrading pump: start the standby pump, then stop the degraded one."""
    target = event["target"]
    other = "pump2" if target == "pump1" else "pump1"
    if reading(snap, other, "status") != "off":
        raise PlanError(f"standby {other} is not available (status {reading(snap, other, 'status')})")
    return {"commanded": [target, other], "affected": [],
            "stages": [
                stage(f"start {other}", {other: {"status": "on"}},
                      [check(other, "status", "eq", "on"), check(other, "flow_lps", "ge", 5.0)],
                      rollback={other: {"status": "off"}}, rollback_note=f"{target} still runs; stop {other}"),
                stage(f"stop {target}", {target: {"status": "off"}},
                      [check(target, "status", "eq", "off"), check(other, "flow_lps", "ge", 35.0),
                       check(other, "vib_mms", "le", 4.5)],
                      rollback={target: {"status": "on"}}, rollback_note=f"{other} alone is not enough; restart {target}"),
            ],
            "ticket": f"Inspect {target} (bearings / impeller); {other} is now duty pump."}


def chilled_water_recovery(event: dict, snap: dict) -> dict:
    """Chilled water supply drifting up: lower the setpoint and start assist capacity."""
    sp = float(reading(snap, "chiller", "sp"))
    return {"commanded": ["chiller"], "affected": [],
            "stages": [stage("lower setpoint and start assist", {"chiller": {"sp": round(sp - 3.0, 1), "assist": "on"}},
                             [check("chiller", "t_sup", "le", sp + 1.0), check("chiller", "assist", "eq", "on")],
                             rollback={"chiller": {"sp": sp, "assist": "off"}},
                             rollback_note="restore the original setpoint")],
            "ticket": f"Chiller supply drifted above {sp:.1f} °C; setpoint lowered and assist started. Service the chiller."}


def hotspot_mitigation(event: dict, snap: dict) -> dict:
    """Hot rack: raise the zone unit's airflow; the workload move is requested in the ticket."""
    target = event["target"]
    zone = zone_of(target)
    crah = f"crah{zone}"
    if reading(snap, crah, "status") != "on":
        raise PlanError(f"{crah} is not running; this needs cooling failover, not a boost")
    return {"commanded": [crah],
            "stages": [stage(f"boost {crah}", {crah: {"fan_pct": 100}}, [check(target, "t_in", "le", INLET_LIMIT_C)],
                             rollback={crah: {"fan_mode": "auto", "fan_pct": None}},
                             rollback_note=f"the boost did not help; {crah} back to automatic")],
            "affected": [f"crah{z}" for z in (zone - 1, zone + 1) if 1 <= z <= N_ZONES],   # extra air spills over
            "ticket": f"Check airflow at {target} (blanking panels, tiles); consider moving its workload."}


def ups_load_transfer(event: dict, snap: dict) -> dict:
    """Overheating UPS battery: move the load to the other UPS (high risk: needs approval)."""
    target = event["target"]
    other = "ups2" if target == "ups1" else "ups1"
    if float(reading(snap, other, "t_batt")) >= 35.0:
        raise PlanError(f"{other} battery is hot too; cannot take the load")
    return {"commanded": [target], "affected": [other],
            "stages": [stage(f"transfer load from {target} to {other}", {target: {"load_share": 0.0}},
                             [check(target, "load_kw", "le", 5.0), check(other, "t_batt", "le", 35.0)],
                             rollback={target: {"load_share": 0.5}},
                             rollback_note=f"{other} cannot carry the load; share it again")],
            "ticket": f"Inspect {target} battery string."}


def rack_power_cap(event: dict, snap: dict) -> dict:
    """PDU near its rating: cap the power of the zone's racks (high risk: needs approval)."""
    target = event["target"]
    zone = int(target[3:])
    racks = zone_racks(zone)
    return {"commanded": racks, "affected": [],
            "stages": [stage(f"cap zone {zone} racks at 40 kW", {r: {"cap_kw": 40} for r in racks},
                             [check(target, "load_pct", "le", 85.0)],
                             rollback_note="hold: removing the caps would raise the load further")],
            "ticket": f"{target} was near its rating; review workload placement before lifting the caps."}


PLAYBOOKS = {
    "cooling_unit_failover": cooling_unit_failover,
    "sensor_quarantine": sensor_quarantine,
    "pump_switchover": pump_switchover,
    "chilled_water_recovery": chilled_water_recovery,
    "hotspot_mitigation": hotspot_mitigation,
    "ups_load_transfer": ups_load_transfer,
    "rack_power_cap": rack_power_cap,
}
assert set(PLAYBOOKS) == {p for _, p in FAULT_CATALOG.values()} - {"notify_only"}


def build_plan(event: dict, snapshot: dict) -> dict:
    """Plan for an anomaly event; raises PlanError when it cannot run safely."""
    name = event["playbook"]
    if name not in PLAYBOOKS:
        raise PlanError(f"no automated playbook for {name}")
    plan = PLAYBOOKS[name](event, snapshot)
    risk, _ = FAULT_CATALOG[event["fault_type"]]
    return {"playbook": name, "risk": risk, "target": event["target"], **plan}


# ---------------------------------------------------------------------------------------- checks
def check_holds(chk: dict, msg: dict) -> bool:
    value = msg["assets"].get(chk["asset"], {}).get(chk["signal"])
    want, op = chk["value"], chk["op"]
    if value is None:
        return False
    if op == "le":
        return float(value) <= want
    if op == "ge":
        return float(value) >= want
    if op == "eq":
        return value == want
    if op == "contains":
        return want in value
    raise ValueError(f"unknown check op {op}")


def evaluate_stage(stg: dict, recent: dict, acted_seq: dict) -> dict:
    """recent: gw -> that gateway's newest messages (newest first); acted_seq: gw -> seq when commanded.

    Returns {"status": "passed" | "pending" | "failed", "since": messages since the commands,
             "failing": [checks not holding on the newest message]}.
    """
    gws = sorted({c["gw"] for c in stg["checks"]})
    newer = {gw: [m for m in recent.get(gw, []) if int(m["seq"]) > int(acted_seq.get(gw, 0))] for gw in gws}
    # messages since the commands, per gateway, measured by sequence number
    counts = [int(newer[gw][0]["seq"]) - int(acted_seq.get(gw, 0)) if newer[gw] else 0 for gw in gws]
    since = min(counts, default=0)
    failing = [c for c in stg["checks"] if not newer[c["gw"]] or not check_holds(c, newer[c["gw"]][0])]
    stable_ok = all(len(newer[gw]) >= stg["stable"] for gw in gws) and all(
        check_holds(c, m) for c in stg["checks"] for m in newer[c["gw"]][:stg["stable"]])
    if stable_ok:
        return {"status": "passed", "since": since, "failing": []}
    if since >= stg["timeout_msgs"]:
        return {"status": "failed", "since": since, "failing": failing}
    return {"status": "pending", "since": since, "failing": failing}
