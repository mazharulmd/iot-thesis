"""Step 5 tests: remediation Lambda steps (moto) and closed-loop playbook runs.

The closed-loop runs use the deployed state machine definition and the real Lambda handler,
with the simulator obeying the shadow commands (experiments/closed_loop.py).
"""
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from experiments.closed_loop import fault_scenario, run_closed_loop

ROOT = Path(__file__).resolve().parents[1]
REGION = "ap-south-1"


@lru_cache(maxsize=None)
def loop(name: str, automation: str = "on"):
    return run_closed_loop(fault_scenario(name), automation=automation)


def log_steps(incident):
    return [s["step"] for s in incident["log"]]


# ---------------------------------------------------------------------------------------- closed loop
def test_crah_failure_is_fixed_and_verified_with_no_human_input():
    r = loop("crah_fan_failure")
    inc = r.incident_for("crah_fan_failure", "crah2")
    assert inc["status"] == "mitigated"
    assert [s for s in log_steps(inc) if s != "correlated"] == [
        "opened", "precheck_passed", "act", "verified", "act", "verified", "closed"]
    assert inc["correlated"] >= 2                                  # side effects joined, no extra alerts
    assert [i for i in r.incidents if i is not inc] == []
    assert all(x["status"] == "SUCCEEDED" for x in r.executions)
    applied = {a for c in r.commands for a in c["applied"] if a != "cmd_id"}
    assert applied == {"crah1", "crah3", "crah5"} and not any(c["errors"] for c in r.commands)
    last = [m for m in r.messages if m["gw"] == "zone2"][-1]
    assert max(v["t_in"] for a, v in last["assets"].items() if a.startswith("rack")) < 27.0
    plant = [m for m in r.messages if m["gw"] == "plant"][-1]["assets"]["crah5"]
    assert plant["status"] == "on" and plant["zone"] == 2
    assert r.alerts == ["[dc-selfheal] Mitigated: cooling_unit_failover on crah2"]


def test_pump_diagnosis_supersedes_an_early_unexplained_alert():
    r = loop("pump_degradation")
    inc = r.incident_for("pump_degradation", "pump1")
    assert inc["status"] == "mitigated" and "supersedes" in log_steps(inc)
    early = r.incident_for("unexplained", "pump1")
    assert early is None or early["status"] == "superseded"
    assert inc["correlated"] > 10                                   # hall-wide side effects grouped
    assert {i["status"] for i in r.incidents} <= {"mitigated", "superseded"}
    last = [m for m in r.messages if m["gw"] == "plant"][-1]["assets"]
    assert last["pump1"]["status"] == "off" and last["pump2"]["flow_lps"] > 35


def test_high_risk_playbook_waits_for_approval_and_sends_no_commands():
    r = loop("ups_battery_overheat")
    inc = r.incident_for("ups_battery_overheat", "ups1")
    assert inc["status"] == "awaiting_approval" and r.commands == []
    assert any("APPROVAL NEEDED" in a for a in r.alerts)
    assert inc["plan"]["stages"][0]["commands"] == {"ups1": {"load_share": 0}}


def test_alert_only_mode_notifies_and_never_commands():
    r = loop("crah_fan_failure", "notify")
    assert r.commands == []
    assert [(i["fault_type"], i["status"]) for i in r.incidents] == [("crah_fan_failure", "notified")]
    assert r.alerts == ["[dc-selfheal] crah_fan_failure on crah2"]


# ---------------------------------------------------------------------------------------- Lambda steps
@pytest.fixture
def lam(monkeypatch):
    for k, v in {"AWS_DEFAULT_REGION": REGION, "INCIDENTS_TABLE": "Incidents", "LOCKS_TABLE": "Locks",
                 "TELEMETRY_TABLE": "Telemetry", "SHADOW_TRANSPORT": "sqs", "POLL_S": "10"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        for name, keys in {"Incidents": ["id", "sk"], "Locks": ["asset"], "Telemetry": ["gw", "ts"]}.items():
            ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                             KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in zip(keys, ["HASH", "RANGE"])],
                             AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in keys])
        q = boto3.client("sqs", region_name=REGION).create_queue(QueueName="shadow")["QueueUrl"]
        monkeypatch.setenv("SHADOW_QUEUE_URL", q)
        spec = importlib.util.spec_from_file_location("rem", ROOT / "lambdas" / "remediation" / "handler.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield mod


def ev(fault, target, playbook, risk="low", ts="2026-12-01T10:00:00.000Z"):
    return {"fault_type": fault, "target": target, "asset": target, "playbook": playbook, "risk": risk,
            "gw": "zone2", "ts": ts, "seq": 1, "evidence": {}}


def call(mod, op, state):
    return json.loads(json.dumps(mod.handler({"op": op, "state": state}, None)))


def test_open_locks_target_and_scope_then_correlates(lam):
    s = call(lam, "open", ev("crah_fan_failure", "crah2", "cooling_unit_failover"))
    assert s["decision"] == "precheck"
    roles = {h["asset"]: h["role"] for h in lam.holders(["crah2", "rack07", "crah1", "chiller"])}
    assert roles == {"crah2": "target", "rack07": "affected", "crah1": "affected"}
    again = call(lam, "open", ev("crah_fan_failure", "crah2", "cooling_unit_failover"))
    assert again["decision"] == "skip" and again["incident_id"] == s["incident_id"]
    side = call(lam, "open", ev("unexplained", "rack07", "notify_only"))
    assert side["decision"] == "skip" and side["incident_id"] == s["incident_id"]
    real = call(lam, "open", ev("rack_hotspot", "rack07", "hotspot_mitigation", "medium"))
    assert real["decision"] == "precheck" and real["incident_id"] != s["incident_id"]   # diagnosed: own incident


def test_diagnosed_fault_supersedes_notify_incident(lam):
    first = call(lam, "open", ev("unexplained", "pump1", "notify_only"))
    assert first["decision"] == "notify"
    call(lam, "notify", first)
    second = call(lam, "open", ev("pump_degradation", "pump1", "pump_switchover", "medium"))
    assert second["decision"] == "precheck"
    old = lam.INCIDENTS.get_item(Key={"id": first["incident_id"], "sk": "A"})["Item"]
    assert old["status"] == "superseded" and old["superseded_by"] == second["incident_id"]
    assert {h["incident_id"] for h in lam.holders(["pump1", "rack03"])} == {second["incident_id"]}


def test_precheck_escalates_when_telemetry_is_missing(lam):
    s = call(lam, "open", ev("chw_supply_drift", "chiller", "chilled_water_recovery", "medium"))
    s = call(lam, "precheck", s)
    assert s["decision"] == "escalate" and "no recent telemetry" in s["reason"]
    s = call(lam, "escalate", s)
    inc = lam.INCIDENTS.get_item(Key={"id": s["incident_id"], "sk": "A"})["Item"]
    assert inc["status"] == "escalated"


def test_alert_only_mode_routes_everything_to_notify(lam, monkeypatch):
    monkeypatch.setattr(lam, "AUTOMATION", "notify")
    s = call(lam, "open", ev("crah_fan_failure", "crah2", "cooling_unit_failover"))
    assert s["decision"] == "notify"
    s = call(lam, "notify", s)
    inc = lam.INCIDENTS.get_item(Key={"id": s["incident_id"], "sk": "A"})["Item"]
    assert inc["status"] == "notified" and "alert-only" in inc["reason"]


def test_prepare_run_removes_future_telemetry_and_queued_commands(monkeypatch):
    from datetime import datetime, timezone

    from tools.prepare_run import drain_queue, purge_future_telemetry, trim_old_telemetry

    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        t = ddb.create_table(TableName="T", BillingMode="PAY_PER_REQUEST",
                             KeySchema=[{"AttributeName": "gw", "KeyType": "HASH"},
                                        {"AttributeName": "ts", "KeyType": "RANGE"}],
                             AttributeDefinitions=[{"AttributeName": "gw", "AttributeType": "S"},
                                                   {"AttributeName": "ts", "AttributeType": "S"}])
        for ts in ("2026-12-01T09:59:00.000Z", "2026-12-01T10:00:00.000Z", "2026-12-01T10:05:00.000Z"):
            t.put_item(Item={"gw": "plant", "ts": ts, "seq": 1})
        now = datetime(2026, 12, 1, 10, 0, 30, tzinfo=timezone.utc)
        assert purge_future_telemetry(t, now) == 1
        assert [i["ts"] for i in t.scan()["Items"]] == ["2026-12-01T09:59:00.000Z", "2026-12-01T10:00:00.000Z"]
        t.put_item(Item={"gw": "zone1", "ts": "2026-12-01T07:00:00.000Z", "seq": 1})
        assert trim_old_telemetry(t, keep_hours=2, now=now) == 1
        assert len(t.scan()["Items"]) == 2
        sqs = boto3.client("sqs", region_name=REGION)
        q = sqs.create_queue(QueueName="q")["QueueUrl"]
        for i in range(13):
            sqs.send_message(QueueUrl=q, MessageBody=json.dumps({"thing": "zone1", "n": i}))
        assert drain_queue(sqs, q) == 13 and drain_queue(sqs, q) == 0
