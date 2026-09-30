"""Step 6 tests: approval wait, rollback, circuit breaker, rate limit, approval Lambda."""
import base64
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

import boto3
import pytest
from moto import mock_aws

import playbooks.catalog as catalog
from experiments.closed_loop import fault_scenario, run_closed_loop
from playbooks.asl import execute
from playbooks.state_machine import definition

ROOT = Path(__file__).resolve().parents[1]
REGION = "ap-south-1"


def steps(incident):
    return [s["step"] for s in incident["log"] if s["step"] != "correlated"]


@lru_cache(maxsize=None)
def ups(decision: str | None):
    op = {"decision": decision, "delay_s": 120} if decision else None
    return run_closed_loop(fault_scenario("ups_battery_overheat"), operator=op, approval_timeout_s=600)


# ---------------------------------------------------------------------------------------- approval (closed loop)
def test_approved_plan_is_rechecked_then_acts_and_verifies():
    r = ups("approve")
    inc = r.incident_for("ups_battery_overheat", "ups1")
    assert inc["status"] == "mitigated"
    assert steps(inc) == ["opened", "precheck_passed", "approval_requested", "rechecked_after_approval",
                          "act", "verified", "closed"]
    assert r.approvals == [{"status": 200, "message": "Plan approved by simulated operator."}]
    assert inc["approval"]["status"] == "approved" and inc["approval"]["decided_by"] == "simulated operator"
    first_command = min(c["t_s"] for c in r.commands)
    detected = next(e["t_s"] for e in r.events if e["fault_type"] == "ups_battery_overheat")
    assert first_command >= detected + 120                     # nothing before the human answered
    assert [m for m in r.messages if m["gw"] == "plant"][-1]["assets"]["ups1"]["load_kw"] < 5


def test_rejected_plan_sends_nothing():
    r = ups("reject")
    inc = r.incident_for("ups_battery_overheat", "ups1")
    assert inc["status"] == "rejected" and "simulated operator" in inc["reason"]
    assert r.commands == [] and steps(inc)[-1] == "rejected"


def test_unanswered_approval_times_out_and_escalates():
    r = ups(None)
    inc = r.incident_for("ups_battery_overheat", "ups1")
    assert inc["status"] == "escalated" and "approval timed out" in inc["reason"]
    assert inc["approval"]["status"] == "expired" and r.commands == []
    ex = next(x for x in r.executions if x["event"] == "ups_battery_overheat:ups1")
    assert ex["status"] == "FAILED"


# ---------------------------------------------------------------------------------------- rollback (closed loop)
def test_failed_verification_rolls_back_and_escalates(monkeypatch):
    monkeypatch.setattr(catalog, "INLET_LIMIT_C", 5.0)              # a check that can never pass
    r = run_closed_loop(fault_scenario("rack_hotspot", after=1200))
    inc = r.incident_for("rack_hotspot", "rack07")
    assert inc["status"] == "escalated"
    assert steps(inc)[-4:] == ["act", "verify_failed", "rolled_back", "escalated"]
    assert "rolled back" in inc["reason"] and inc["rolled_back"] is True
    boost, undo = [c for c in r.commands if "crah2" in c["applied"]][:2]
    assert boost["applied"]["crah2"]["fan_mode"] == "manual"
    assert undo["desired"]["cmd_id"].endswith(":rollback:zone2") and undo["applied"]["crah2"]["fan_mode"] == "auto"
    assert any("ESCALATED" in a for a in r.alerts)


# ---------------------------------------------------------------------------------------- Lambda level
@pytest.fixture
def aws(monkeypatch):
    env = {"AWS_DEFAULT_REGION": REGION, "INCIDENTS_TABLE": "Incidents", "LOCKS_TABLE": "Locks",
           "TELEMETRY_TABLE": "Telemetry", "GUARDRAILS_TABLE": "Guardrails", "SHADOW_TRANSPORT": "sqs",
           "MAX_ACTIONS_PER_HOUR": "3", "BREAKER_FAILURES": "2", "APPROVAL_URL": "https://approve.example/"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        for name, keys in {"Incidents": ["id", "sk"], "Locks": ["asset"], "Telemetry": ["gw", "ts"],
                           "Guardrails": ["key"]}.items():
            ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                             KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in zip(keys, ["HASH", "RANGE"])],
                             AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in keys])
        q = boto3.client("sqs", region_name=REGION).create_queue(QueueName="shadow")["QueueUrl"]
        monkeypatch.setenv("SHADOW_QUEUE_URL", q)
        mods = {}
        for name in ("remediation", "approval"):
            spec = importlib.util.spec_from_file_location(f"g_{name}", ROOT / "lambdas" / name / "handler.py")
            mods[name] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mods[name])
        yield mods["remediation"], mods["approval"]


PLAN = {"playbook": "hotspot_mitigation", "risk": "medium", "target": "rack07", "commanded": ["crah2"],
        "affected": [], "stages": [], "ticket": ""}


def test_two_failed_verifications_open_the_circuit_breaker(aws):
    rem, _ = aws
    assert rem.guardrail_block(PLAN, "inc-a") is None
    assert rem.record_failure("rack07", "inc-a", "x") is False
    assert rem.guardrail_block(PLAN, "inc-b") is None
    assert rem.record_failure("rack07", "inc-b", "x") is True
    assert "circuit breaker open for rack07: 2 failed" in rem.guardrail_block(PLAN, "inc-c")
    rem.record_success("rack07")                                     # e.g. make reset-breaker after repair
    assert rem.guardrail_block(PLAN, "inc-d") is None


def test_rate_limit_counts_incidents_not_stages(aws):
    rem, _ = aws
    for inc in ("i1", "i1", "i2", "i3"):                              # i1 has two stages: counted once
        rem.record_action("crah2", inc)
    assert len(rem.recent_actions("crah2")) == 3
    assert "rate limit: crah2 already had 3" in rem.guardrail_block(PLAN, "i4")
    assert rem.guardrail_block(PLAN, "i3") is None                    # its own actions do not count
    rem.now = lambda: __import__("time").time() + 3700                # an hour later
    assert rem.guardrail_block(PLAN, "i4") is None


def test_approval_lambda_page_decision_and_single_use(aws):
    rem, appr = aws
    rem.INCIDENTS.put_item(Item={"id": "inc1", "sk": "A", "fault_type": "pdu_overload", "target": "pdu3",
                                 "plan": {"risk": "high", "playbook": "rack_power_cap",
                                          "stages": [{"name": "cap", "commands": {"rack11": {"cap_kw": 40}}}]}})
    rem.op_request_approval({"incident_id": "inc1", "plan": {**PLAN, "risk": "high", "stages": []},
                             "_task_token": "tok-1"})
    item = rem.INCIDENTS.get_item(Key={"id": "inc1", "sk": "APPROVAL"})["Item"]
    assert item["status"] == "pending" and len(item["nonce"]) >= 32

    sent = []

    class FakeSfn:
        def send_task_success(self, taskToken, output):
            sent.append((taskToken, json.loads(output)))

    appr.SFN = FakeSfn()
    get = {"requestContext": {"http": {"method": "GET"}},
           "queryStringParameters": {"incident": "inc1", "nonce": item["nonce"]}}
    page = appr.handler(get, None)
    assert page["statusCode"] == 200 and "Approve" in page["body"] and "rack11" in page["body"] and not sent
    bad = appr.handler({**get, "queryStringParameters": {"incident": "inc1", "nonce": "guess"}}, None)
    assert bad["statusCode"] == 403

    form = urlencode({"incident": "inc1", "nonce": item["nonce"], "decision": "approve", "by": "Tusar"})
    post = {"requestContext": {"http": {"method": "POST"}}, "body": base64.b64encode(form.encode()).decode(),
            "isBase64Encoded": True}
    assert appr.handler(post, None)["statusCode"] == 200
    assert sent == [("tok-1", {"decision": "approved", "by": "Tusar", "at": sent[0][1]["at"]})]
    assert appr.handler(post, None)["statusCode"] == 409                # single use
    assert rem.INCIDENTS.get_item(Key={"id": "inc1", "sk": "APPROVAL"})["Item"]["decided_by"] == "Tusar"


def test_expired_approval_is_refused(aws):
    rem, appr = aws
    rem.INCIDENTS.put_item(Item={"id": "inc2", "sk": "A"})
    rem.op_request_approval({"incident_id": "inc2", "plan": {**PLAN, "risk": "high"}, "_task_token": "tok-2"})
    nonce = rem.INCIDENTS.get_item(Key={"id": "inc2", "sk": "APPROVAL"})["Item"]["nonce"]
    appr.now = lambda: __import__("time").time() + 4000
    assert appr.handler({"incident": "inc2", "nonce": nonce, "decision": "approve"}, None)["status"] == 410


# ---------------------------------------------------------------------------------------- state machine
def _gen_until_token():
    def invoke(resource, payload):
        state = payload["state"]
        if payload["op"] == "open":
            return {**state, "decision": "precheck", "poll_s": 5, "incident_id": "i"}
        if payload["op"] == "precheck":
            approved = (state.get("approval") or {}).get("decision") == "approved"
            return {**state, "decision": "act" if approved else "approval"}
        if payload["op"] == "request_approval":
            assert payload["task_token"]
            return {"requested": True}
        if payload["op"] == "verify":
            return {**state, "decision": "passed"}
        return {**state, "decision": "done"}

    gen = execute(definition("fn", 60), {"fault_type": "x"}, invoke)
    step = next(gen)
    assert step[0] == "token" and step[2] == 60
    return gen


def test_state_machine_approval_paths():
    gen = _gen_until_token()
    assert gen.send(("success", {"decision": "approved", "by": "a"})) == ("wait", 5.0)
    with pytest.raises(StopIteration) as stop:
        next(gen)
    assert stop.value.value[0] == "SUCCEEDED" and stop.value.value[2][-2:] == ["Close", "Mitigated"]

    gen = _gen_until_token()
    with pytest.raises(StopIteration) as stop:
        gen.send(("success", {"decision": "rejected", "by": "a"}))
    assert stop.value.value[2][-2:] == ["Reject", "Rejected"]

    gen = _gen_until_token()
    with pytest.raises(StopIteration) as stop:
        gen.send(("timeout",))
    status, _, history = stop.value.value
    assert status == "FAILED" and history[-3:] == ["RequestApproval", "Escalate", "Escalated"]


def test_every_stage_has_a_rollback_decision():
    snap_path = ROOT / "tests" / "test_playbooks.py"
    assert snap_path.exists()
    from tests.test_playbooks import event, normal_snapshot
    import copy
    snap = copy.deepcopy(normal_snapshot())
    snap["zone2"]["assets"]["crah2"].update(status="failed", fan_pct=0.0)
    cases = [event("crah_fan_failure", "crah2", "cooling_unit_failover"),
             event("sensor_stuck", "rack07", "sensor_quarantine", {"signal": "t_in"}),
             event("pump_degradation", "pump1", "pump_switchover"),
             event("chw_supply_drift", "chiller", "chilled_water_recovery"),
             event("rack_hotspot", "rack12", "hotspot_mitigation"),
             event("ups_battery_overheat", "ups1", "ups_load_transfer"),
             event("pdu_overload", "pdu3", "rack_power_cap")]
    for ev in cases:
        for st in catalog.build_plan(ev, snap)["stages"]:
            assert st["rollback"] or st["rollback_note"].startswith("hold"), (ev["playbook"], st["name"])
            assert set(st["rollback"]) <= set(catalog.build_plan(ev, snap)["commanded"])
