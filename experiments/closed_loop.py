"""Closed-loop run without AWS or MQTT: simulator + detector + remediation state machine.

The same pieces as the deployed pipeline, wired together in one process:

  simulator (physics, faults, sensors)
    -> telemetry, stored in a mocked Telemetry table (moto)
    -> detection engine (the detector Lambda's code path)
    -> remediation state machine: the deployed definition, run by playbooks/asl.py,
       calling the real remediation Lambda handler against mocked DynamoDB / SQS / SNS
    -> shadow commands on the mocked queue -> shadow store -> simulator applies them

Time is simulated: a Wait state of N seconds resumes the execution N simulated seconds later,
and the Lambda's clock is the simulation clock. High-risk plans wait for approval: a simulated
operator answers through the real approval Lambda after `delay_s` (approve or reject), or never,
in which case the approval times out. Used by the tests and for quick playbook checks:

    python -m experiments.closed_loop --scenario crah_fan_failure [--automation notify] [--fault-at 600]
    python -m experiments.closed_loop --scenario ups_battery_overheat --operator approve --operator-delay 120
"""
from __future__ import annotations

import argparse
import heapq
import importlib.util
import itertools
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import boto3
import numpy as np
from botocore.exceptions import ClientError
from moto import mock_aws

from bridge.shadow import ShadowStore
from common.topology import GATEWAYS, gateway_of
from detection.engine import DetectionEngine
from detection.models import Bundle
from playbooks.asl import execute
from playbooks.catalog import PlanError, build_plan
from playbooks.state_machine import definition
from simulator.config import HallConfig, ScenarioConfig
from simulator.faults import SensorLayer, apply_physical_faults
from simulator.model import DataHall
from simulator.runner import load_scenario

ROOT = Path(__file__).resolve().parents[1]
REGION = "ap-south-1"
FN = "arn:aws:lambda:ap-south-1:000000000000:function:remediation"
META_KEYS = {"cmd_id", "issued_at", "applied_at", "errors"}


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class ClosedLoopResult:
    scenario: str
    labels: list = field(default_factory=list)
    events: list = field(default_factory=list)
    executions: list = field(default_factory=list)
    incidents: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    messages: list = field(default_factory=list)       # everything the gateways published
    approvals: list = field(default_factory=list)
    truth: list = field(default_factory=list)          # true (noise-free) readings at each publish
    human_actions: list = field(default_factory=list)  # M1: what the simulated operator did
    dropped: int = 0

    def incident_for(self, fault_type: str, target: str) -> dict | None:
        return next((i for i in self.incidents if i["fault_type"] == fault_type and i["target"] == target), None)

    def series(self, gw: str, asset: str, signal: str) -> list[tuple[float, float]]:
        return [(m["t_s"], m["assets"][asset][signal]) for m in self.messages if m["gw"] == gw]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_handler", ROOT / "lambdas" / name / "handler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeStepFunctions:
    """Stands in for the Step Functions API in the approval Lambda: answers go to the runner."""

    def __init__(self):
        self.pending: set[str] = set()
        self.replies: list[tuple[str, tuple]] = []

    def send_task_success(self, taskToken: str, output: str) -> dict:
        if taskToken not in self.pending:
            raise ClientError({"Error": {"Code": "TaskTimedOut", "Message": "timed out"}}, "SendTaskSuccess")
        self.pending.discard(taskToken)
        self.replies.append((taskToken, ("success", json.loads(output))))
        return {}


def _create_resources() -> dict:
    ddb = boto3.client("dynamodb", region_name=REGION)

    def table(name, hk, rk=None):
        ks = [{"AttributeName": hk, "KeyType": "HASH"}] + ([{"AttributeName": rk, "KeyType": "RANGE"}] if rk else [])
        ad = [{"AttributeName": a, "AttributeType": "S"} for a in [hk] + ([rk] if rk else [])]
        ddb.create_table(TableName=name, KeySchema=ks, AttributeDefinitions=ad, BillingMode="PAY_PER_REQUEST")

    table("Telemetry", "gw", "ts")
    table("Incidents", "id", "sk")
    table("Locks", "asset")
    table("Guardrails", "key")
    sqs, sns = boto3.client("sqs", region_name=REGION), boto3.client("sns", region_name=REGION)
    shadow_q = sqs.create_queue(QueueName="shadow-updates")["QueueUrl"]
    alerts_q = sqs.create_queue(QueueName="alerts")["QueueUrl"]
    topic = sns.create_topic(Name="alerts")["TopicArn"]
    arn = sqs.get_queue_attributes(QueueUrl=alerts_q, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=arn)
    return {"shadow_q": shadow_q, "alerts_q": alerts_q, "topic": topic}


def _drain(sqs, url: str) -> list[dict]:
    out = []
    while True:
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
        if not msgs:
            return out
        for m in msgs:
            out.append(json.loads(m["Body"]))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])


def run_closed_loop(scn: ScenarioConfig, *, detector: str = "d2h", automation: str = "on", poll_s: int = 10,
                    operator: dict | None = None, approval_timeout_s: int = 1800, human: dict | None = None,
                    drop_rate: float = 0.0, cfg: HallConfig | None = None) -> ClosedLoopResult:
    """operator: None (nobody answers approvals) or {"decision": "approve"|"reject", "delay_s": seconds}.
    human:    alert-only mode (M1): {"delay_s": s, "stage_gap_s": s} - after an alert with a diagnosed
              fault, the operator carries out the same playbook by hand, stage by stage.
    drop_rate: probability that a gateway message never reaches the cloud (E4)."""
    cfg = cfg or HallConfig()
    env = {"AWS_DEFAULT_REGION": REGION, "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
           "INCIDENTS_TABLE": "Incidents", "LOCKS_TABLE": "Locks", "TELEMETRY_TABLE": "Telemetry",
           "GUARDRAILS_TABLE": "Guardrails", "APPROVAL_TIMEOUT_S": str(approval_timeout_s),
           "SHADOW_TRANSPORT": "sqs", "AUTOMATION": automation, "POLL_S": str(poll_s), "FRESH_S": "120"}
    saved = {k: os.environ.get(k) for k in [*env, "ALERTS_TOPIC", "SHADOW_QUEUE_URL", "AWS_ENDPOINT_URL"]}
    os.environ.update(env)
    os.environ.pop("AWS_ENDPOINT_URL", None)
    try:
        with mock_aws():
            res = _create_resources()
            os.environ["ALERTS_TOPIC"], os.environ["SHADOW_QUEUE_URL"] = res["topic"], res["shadow_q"]
            return _run(scn, cfg, detector, res, operator, approval_timeout_s, human, drop_rate)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _run(scn: ScenarioConfig, cfg: HallConfig, detector: str, res: dict, operator: dict | None,
         approval_timeout_s: int, human: dict | None, drop_rate: float) -> ClosedLoopResult:
    rem, appr = _load("remediation"), _load("approval")
    start = datetime.fromisoformat(scn.start_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    clock = {"t": 0.0}
    rem.now = appr.now = lambda: start.timestamp() + clock["t"]
    sfn = appr.SFN = _FakeStepFunctions()
    sqs = boto3.client("sqs", region_name=REGION)
    ddb = boto3.resource("dynamodb", region_name=REGION)
    telemetry = ddb.Table("Telemetry")
    defn = definition(FN, approval_timeout_s)

    def invoke(resource: str, payload: dict) -> dict:
        assert resource == FN, resource
        return json.loads(json.dumps(rem.handler(json.loads(json.dumps(payload)), None)))

    rng = np.random.default_rng(scn.seed)
    hall = DataHall(cfg, rng)
    hall.t = -scn.warmup_s
    hall.init_load(scn.initial_busy_frac)
    sensors = SensorLayer(hall, scn.faults, np.random.default_rng(scn.seed + 10_000))
    while hall.t < 0:
        hall.step(cfg.dt_s)
    hall.t = 0.0

    out = ClosedLoopResult(scenario=scn.name,
                           labels=[{"type": f.type, "target": f.target, "start_s": f.start_s,
                                    "normal_event": f.is_normal_event} for f in scn.faults])
    drop_rng = np.random.default_rng(scn.seed + 20_000)
    engine = DetectionEngine(Bundle.load(), detector)
    history: dict[str, list] = {gw: [] for gw in GATEWAYS}
    store = ShadowStore()
    waiting: list = []                            # (time, n, kind, data): resume / operator / timeout
    counter = itertools.count()
    tokens: dict[str, tuple] = {}                 # task token -> (entry, gen) waiting for approval
    seq = {gw: 0 for gw in GATEWAYS}
    last_seen: dict[str, list] = {gw: [] for gw in GATEWAYS}   # what the operator's BMS screen shows
    next_publish = 0.0

    def advance(entry: dict, gen, reply=None) -> None:
        try:
            step = gen.send(reply) if reply is not None else next(gen)
        except StopIteration as stop:
            entry["status"], entry["output"], entry["history"] = stop.value
            entry["ended_s"] = clock["t"]
            ev = (entry["output"] or {}).get("event") or {}
            if human and entry["history"][-1] == "Notified" and ev.get("playbook", "notify_only") != "notify_only":
                heapq.heappush(waiting, (clock["t"] + human["delay_s"], next(counter), "human", (ev, None, 0)))
            return
        if step[0] == "wait":
            heapq.heappush(waiting, (clock["t"] + step[1], next(counter), "resume", (entry, gen)))
        else:                                                   # ("token", token, timeout)
            token, timeout = step[1], step[2]
            tokens[token] = (entry, gen)
            sfn.pending.add(token)
            if operator:
                heapq.heappush(waiting, (clock["t"] + operator.get("delay_s", 120), next(counter), "operator", token))
            heapq.heappush(waiting, (clock["t"] + (timeout or 1e12), next(counter), "timeout", token))

    def human_acts(ev: dict, plan: dict | None, k: int) -> None:
        """M1: the operator read the alert and now does the playbook's stage k by hand (via the BMS)."""
        if plan is None:
            snap = {gw: h[-1] for gw, h in last_seen.items() if h}
            try:
                plan = build_plan(ev, snap)
            except PlanError as exc:
                out.human_actions.append({"t_s": clock["t"], "event": f"{ev['fault_type']}:{ev['target']}",
                                          "action": "none", "reason": str(exc)})
                return
        stg = plan["stages"][k]
        by_gw: dict = {}
        for asset, desired in stg["commands"].items():
            by_gw.setdefault(gateway_of(asset), {})[asset] = desired
        for gw, desired in by_gw.items():
            apply_shadow({"thing": gw, "payload": {"state": {"desired": {**desired, "cmd_id": f"human:{k}:{gw}"}}}})
        out.human_actions.append({"t_s": clock["t"], "event": f"{ev['fault_type']}:{ev['target']}",
                                  "action": stg["name"], "commands": stg["commands"]})
        if k + 1 < len(plan["stages"]):
            heapq.heappush(waiting, (clock["t"] + human.get("stage_gap_s", 120), next(counter), "human",
                                     (ev, plan, k + 1)))

    def operator_answers(token: str) -> None:
        items = ddb.Table("Incidents").scan()["Items"]
        item = next((i for i in items if i["sk"] == "APPROVAL" and i.get("token") == token), None)
        if item:
            out.approvals.append(appr.handler({"incident": item["id"], "nonce": item["nonce"],
                                               "decision": operator["decision"], "by": "simulated operator"}, None))
        for tok, reply in sfn.replies:
            if tok in tokens:
                entry, gen = tokens.pop(tok)
                advance(entry, gen, reply)
        sfn.replies.clear()

    def apply_shadow(update: dict) -> None:
        gw, desired = update["thing"], update["payload"]["state"]["desired"]
        _, delta = store.update(gw, {"desired": desired})
        reported, errors = {}, {}
        for asset, want in delta.items():
            if asset in META_KEYS or not isinstance(want, dict):
                continue
            try:
                hall.apply_command(asset, want)
                reported[asset] = hall.controls(asset)
            except (ValueError, StopIteration) as exc:
                errors[asset] = str(exc)
        if desired.get("cmd_id"):
            reported["cmd_id"] = desired["cmd_id"]
        store.update(gw, {"reported": reported})
        out.commands.append({"t_s": clock["t"], "gw": gw, "desired": desired, "applied": reported, "errors": errors})

    for _ in range(int(round(scn.duration_s / cfg.dt_s)) + 1):
        t = clock["t"] = hall.t
        while waiting and waiting[0][0] <= t + 1e-9:
            _, _, kind, data = heapq.heappop(waiting)
            if kind == "resume":
                advance(*data)
            elif kind == "operator" and data in tokens:
                operator_answers(data)
            elif kind == "timeout" and data in tokens:
                sfn.pending.discard(data)
                entry, gen = tokens.pop(data)
                advance(entry, gen, ("timeout",))
            elif kind == "human":
                human_acts(*data)
        for update in _drain(sqs, res["shadow_q"]):
            apply_shadow(update)
        if t >= next_publish - 1e-9:
            readings = sensors.measure(t)
            out.truth.append({"t_s": t, "values": _plain_floats(hall.true_readings()),
                              "wall_start": scn.start_time})
            now_iso = iso(start + timedelta(seconds=t))
            for gw in GATEWAYS:
                seq[gw] += 1
                msg = {"gw": gw, "ts": now_iso, "seq": seq[gw], "sent_at": now_iso, "received_at": now_iso,
                       "assets": readings[gw]}
                out.messages.append({**msg, "t_s": t})
                last_seen[gw] = [msg]
                if drop_rate and drop_rng.random() < drop_rate:
                    out.dropped += 1                         # lost between gateway and cloud
                    continue
                telemetry.put_item(Item=json.loads(json.dumps(msg), parse_float=Decimal))
                if history[gw] and history[gw][-1]["seq"] != msg["seq"] - 1:
                    history[gw] = []                         # like the Lambda: history stops at a gap
                history[gw].append(msg)
                del history[gw][:-engine.messages_needed]
                for e in engine.process(history[gw]):
                    e["t_s"] = t
                    out.events.append(e)
                    entry = {"event": f"{e['fault_type']}:{e['target']}", "asset": e["asset"], "started_s": t}
                    out.executions.append(entry)
                    advance(entry, execute(defn, e, invoke))
            next_publish += cfg.publish_period_s
        apply_physical_faults(hall, scn.faults, t)
        hall.step(cfg.dt_s)

    items = [rem.plain(i) for i in ddb.Table("Incidents").scan()["Items"]]
    for summary in sorted((i for i in items if i["sk"] == "A"), key=lambda i: i["opened_at"]):
        summary["log"] = sorted((i for i in items if i["id"] == summary["id"] and i["sk"].startswith("L#")),
                                key=lambda i: i["sk"])
        summary["approval"] = next((i for i in items if i["id"] == summary["id"] and i["sk"] == "APPROVAL"), None)
        out.incidents.append(summary)
    for body in _drain(sqs, res["alerts_q"]):
        out.alerts.append(body.get("Subject"))
    return out


def _plain_floats(value):
    if isinstance(value, dict):
        return {k: _plain_floats(v) for k, v in value.items()}
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    return value


def fault_scenario(name: str, fault_at: float = 600.0, after: float = 1500.0, seed: int | None = None) -> ScenarioConfig:
    """A fault scenario from simulator/scenarios, with the fault moved earlier and no scripted actions."""
    scn, _ = load_scenario(ROOT / "simulator" / "scenarios" / f"{name}.yaml")
    for f in scn.faults:
        f.start_s = fault_at
    scn.duration_s = fault_at + after
    scn.actions = []
    if seed is not None:
        scn.seed = seed
    return scn


def summarize(res: ClosedLoopResult) -> str:
    lines = [f"scenario {res.scenario}: " + ", ".join(f"{lab['type']} on {lab['target']} at {lab['start_s']:.0f} s"
                                                     for lab in res.labels)]
    lines.append(f"events: {len(res.events)}  executions: " + ", ".join(
        f"{x['event']}->{x.get('status', 'RUNNING')}" for x in res.executions))
    for inc in res.incidents:
        lines.append(f"\nincident {inc['id']}  {inc['fault_type']} on {inc['target']}  status={inc['status']}"
                     f"  correlated={inc.get('correlated', 0)}")
        for entry in inc["log"]:
            detail = {k: v for k, v in entry.items() if k not in ("id", "sk", "step", "at", "event", "acted_seq")}
            lines.append(f"  {entry['at'][11:19]}  {entry['step']:16s} {json.dumps(detail, default=str)[:160]}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Closed-loop playbook run (no AWS needed)")
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--detector", default="d2h")
    ap.add_argument("--automation", default="on", choices=["on", "notify"])
    ap.add_argument("--fault-at", type=float, default=600.0)
    ap.add_argument("--after", type=float, default=1500.0)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--operator", choices=["approve", "reject", "none"], default="approve",
                    help="how the simulated operator answers approval requests")
    ap.add_argument("--operator-delay", type=float, default=120.0, help="seconds until the operator answers")
    ap.add_argument("--approval-timeout", type=int, default=1800)
    args = ap.parse_args()
    op = None if args.operator == "none" else {"decision": args.operator, "delay_s": args.operator_delay}
    res = run_closed_loop(fault_scenario(args.scenario, args.fault_at, args.after, args.seed),
                          detector=args.detector, automation=args.automation, operator=op,
                          approval_timeout_s=args.approval_timeout)
    print(summarize(res))
    sys.exit(0)


if __name__ == "__main__":
    main()
