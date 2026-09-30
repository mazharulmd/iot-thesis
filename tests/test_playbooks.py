"""Step 5 unit tests: playbook plans, stage verification, dependency scope, state machine, ASL runner."""
import copy
from functools import lru_cache

import numpy as np
import pytest

from common.topology import GATEWAYS, downstream
from detection.features import base_signals
from playbooks.asl import execute
from playbooks.catalog import PLAYBOOKS, PlanError, build_plan, check, evaluate_stage
from playbooks.state_machine import definition
from simulator.config import HallConfig, ScenarioConfig
from simulator.faults import SensorLayer
from simulator.model import DataHall
from simulator.runner import run_scenario


@lru_cache(maxsize=None)
def normal_snapshot() -> dict:
    msgs = run_scenario(ScenarioConfig(duration_s=60, seed=3)).messages
    return {gw: next(m for m in reversed(msgs) if m["gw"] == gw) for gw in GATEWAYS}


def event(fault, target, playbook, evidence=None):
    return {"fault_type": fault, "target": target, "asset": target, "playbook": playbook, "evidence": evidence or {}}


# ---------------------------------------------------------------------------------------- plans
def test_every_automated_playbook_builds_a_plan():
    snap = copy.deepcopy(normal_snapshot())
    snap["zone2"]["assets"]["crah2"].update(status="failed", fan_pct=0.0)
    cases = [("crah_fan_failure", "crah2", "cooling_unit_failover", None),
             ("sensor_stuck", "rack07", "sensor_quarantine", {"signal": "t_in"}),
             ("pump_degradation", "pump1", "pump_switchover", None),
             ("chw_supply_drift", "chiller", "chilled_water_recovery", None),
             ("rack_hotspot", "rack12", "hotspot_mitigation", None),
             ("ups_battery_overheat", "ups1", "ups_load_transfer", None),
             ("pdu_overload", "pdu3", "rack_power_cap", None)]
    assert {c[2] for c in cases} == set(PLAYBOOKS)
    for fault, target, playbook, ev in cases:
        plan = build_plan(event(fault, target, playbook, ev), snap)
        assert plan["stages"] and plan["commanded"], playbook
        for st in plan["stages"]:
            assert st["checks"] and set(st["commands"]) <= set(plan["commanded"]), playbook
    assert build_plan(event("ups_battery_overheat", "ups1", "ups_load_transfer"), snap)["risk"] == "high"


def test_cooling_failover_plan_details():
    snap = copy.deepcopy(normal_snapshot())
    snap["zone2"]["assets"]["crah2"].update(status="failed", fan_pct=0.0)
    plan = build_plan(event("crah_fan_failure", "crah2", "cooling_unit_failover"), snap)
    first, second = plan["stages"]
    assert first["commands"] == {"crah1": {"fan_pct": 100}, "crah3": {"fan_pct": 100},
                                 "crah5": {"status": "on", "zone": 2, "fan_pct": 90}}
    assert second["commands"]["crah5"] == {"fan_mode": "auto", "fan_pct": None}
    assert {c["asset"] for c in first["checks"]} >= {"rack06", "rack10", "crah5"}
    snap["plant"]["assets"]["crah5"]["status"] = "on"             # standby already busy elsewhere
    plan = build_plan(event("crah_fan_failure", "crah2", "cooling_unit_failover"), snap)
    assert len(plan["stages"]) == 1 and "crah5" not in plan["commanded"]


@pytest.mark.parametrize("mutate, ev, match", [
    (lambda s: s["plant"]["assets"]["pump2"].update(status="on"),
     event("pump_degradation", "pump1", "pump_switchover"), "standby pump2"),
    (lambda s: s["zone2"]["assets"]["crah2"].update(status="failed"),
     event("rack_hotspot", "rack07", "hotspot_mitigation"), "cooling failover"),
    (lambda s: None, event("crah_fan_failure", "crah2", "cooling_unit_failover"), "running again"),
    (lambda s: s.pop("plant"), event("chw_supply_drift", "chiller", "chilled_water_recovery"), "no recent telemetry"),
    (lambda s: None, event("unexplained", "rack01", "notify_only"), "no automated playbook"),
])
def test_unsafe_situations_raise_plan_error(mutate, ev, match):
    snap = copy.deepcopy(normal_snapshot())
    mutate(snap)
    with pytest.raises(PlanError, match=match):
        build_plan(ev, snap)


def test_stage_verification_needs_stable_messages_after_the_command():
    stg = {"checks": [check("rack07", "t_in", "le", 27.0)], "stable": 3, "timeout_msgs": 5}

    def msgs(temps, first_seq):
        return [{"seq": first_seq + i, "assets": {"rack07": {"t_in": t}}} for i, t in enumerate(temps)][::-1]

    acted = {"zone2": 10}
    assert evaluate_stage(stg, {"zone2": msgs([25, 25, 25], 8)}, acted)["status"] == "pending"   # 2 are old
    assert evaluate_stage(stg, {"zone2": msgs([30, 25, 25, 25], 11)}, acted)["status"] == "passed"
    r = evaluate_stage(stg, {"zone2": msgs([25, 30, 25], 12)}, acted)
    assert r["status"] == "pending" and r["since"] == 4
    r = evaluate_stage(stg, {"zone2": msgs([30, 30, 30], 13)}, acted)
    assert r["status"] == "failed" and r["failing"][0]["asset"] == "rack07"


def test_contains_and_eq_checks():
    stg = {"checks": [check("rack07", "quarantined", "contains", "t_in"), check("crah2", "status", "eq", "on")],
           "stable": 1, "timeout_msgs": 3}
    m = {"seq": 2, "assets": {"rack07": {"quarantined": ["t_in"]}, "crah2": {"status": "on"}}}
    assert evaluate_stage(stg, {"zone2": [m]}, {"zone2": 1})["status"] == "passed"


# ---------------------------------------------------------------------------------------- scope
def test_dependency_scope():
    assert set(downstream("chiller")) >= {"rack01", "rack20", "crah1", "crah5", "pump1", "pump2"}
    assert downstream("crah2") == ["rack06", "rack07", "rack08", "rack09", "rack10", "pdu2", "crah1", "crah3"]
    assert downstream("crah4")[-1] == "crah3"
    assert downstream("pdu3") == ["rack11", "rack12", "rack13", "rack14", "rack15", "crah3"]
    assert downstream("rack07") == [] and downstream("ups1") == ["ups2"]


# ---------------------------------------------------------------------------------------- state machine
def test_state_machine_is_well_formed():
    d = definition("fn")
    states = d["States"]
    for name, st in states.items():
        for nxt in [st.get("Next"), st.get("Default"), *[c["Next"] for c in st.get("Choices", [])],
                    *[c["Next"] for c in st.get("Catch", [])]]:
            assert nxt is None or nxt in states, (name, nxt)
        if st["Type"] == "Task" and name != "Escalate":
            assert st["Catch"][0]["Next"] == "Escalate", name
    reachable, todo = set(), [d["StartAt"]]
    while todo:
        n = todo.pop()
        if n in reachable:
            continue
        reachable.add(n)
        st = states[n]
        todo += [x for x in [st.get("Next"), st.get("Default"), *[c["Next"] for c in st.get("Choices", [])],
                             *[c["Next"] for c in st.get("Catch", [])]] if x]
    assert reachable == set(states)
    assert states["WaitForEffect"]["SecondsPath"] == "$.poll_s"


def test_asl_runner_follows_catch_and_waits():
    calls = []

    def invoke(resource, payload):
        calls.append(payload["op"])
        state = payload["state"]
        if payload["op"] == "open":
            return {**state, "decision": "precheck", "poll_s": 7}
        if payload["op"] == "precheck":
            return {**state, "decision": "act"}
        if payload["op"] == "act":
            return state
        if payload["op"] == "verify":
            raise RuntimeError("telemetry query failed")
        return {**state, "decision": "done"}

    gen = execute(definition("fn"), {"fault_type": "x"}, invoke)
    assert next(gen) == ("wait", 7.0)
    with pytest.raises(StopIteration) as stop:
        next(gen)
    status, output, history = stop.value.value
    assert status == "FAILED" and history[-2:] == ["Escalate", "Escalated"]
    assert calls == ["open", "precheck", "act", "verify", "escalate"]


# ---------------------------------------------------------------------------------------- simulator + detector
def test_gateway_reports_full_controllable_state():
    hall = DataHall(HallConfig(), np.random.default_rng(0))
    hall.apply_command("crah1", {"fan_pct": 100})
    assert hall.controls("crah1") == {"status": "on", "fan_mode": "manual", "fan_pct": 100.0}
    hall.apply_command("crah1", {"fan_mode": "auto"})
    assert hall.controls("crah1") == {"status": "on", "fan_mode": "auto", "fan_pct": None}
    hall.apply_command("crah5", {"status": "on", "zone": 2, "fan_pct": 90})
    assert hall.controls("crah5") == {"status": "starting", "fan_mode": "manual", "fan_pct": 90.0, "zone": 2}
    assert hall.controls("rack07") == {"cap_kw": None, "sensor_flag": None}
    hall.apply_command("rack07", {"sensor_flag": "t_in"})
    assert hall.controls("rack07")["sensor_flag"] == "t_in"
    assert hall.controls("ups1") == {"load_share": 0.5} and hall.controls("pump2") == {"status": "off"}


def test_quarantined_sensor_is_published_and_imputed():
    hall = DataHall(HallConfig(), np.random.default_rng(0))
    hall.init_load(0.5)
    for _ in range(300):
        hall.step(1.0)
    hall.apply_command("rack07", {"sensor_flag": "t_in"})
    readings = SensorLayer(hall, [], np.random.default_rng(1)).measure(0.0)
    assert readings["zone2"]["rack07"]["quarantined"] == ["t_in"]
    msg = {"gw": "zone2", "assets": copy.deepcopy(readings["zone2"])}
    msg["assets"]["rack07"]["t_in"] = 99.0                       # the broken sensor's value is ignored
    sig = base_signals(msg)
    peers = [readings["zone2"][r]["t_in"] for r in ("rack06", "rack08", "rack09", "rack10")]
    assert sig["rack07"][1][0] == pytest.approx(float(np.median(peers)))
    msg["assets"]["pdu2"]["quarantined"] = ["load_pct"]
    assert "pdu2" not in base_signals(msg)
