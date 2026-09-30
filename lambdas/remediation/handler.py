"""Remediation Lambda: every step of the remediation state machine (playbooks/state_machine.py).

Called as {"op": <step>, "state": <execution state>} and returns the new state. Steps:

  open              join an open incident if the asset is already locked/muted (correlation),
                    otherwise create the incident and lock the target asset
  notify            no automated playbook (or automation off): alert a human
  precheck          build the plan from the latest telemetry, apply the guardrails (circuit breaker,
                    rate limit), lock the assets it will command, route high-risk plans to approval;
                    after an approval it runs again on fresh telemetry before anything is sent
  request_approval  high risk: store the task token, alert a human with a one-time approval link;
                    the execution waits until the approval Lambda answers or the wait times out
  reject            the human rejected the plan: close the incident, nothing was sent
  act               send the stage's commands as device-shadow desired state
  verify            check the stage's conditions on telemetry sent after the commands
  rollback          verification failed: send the stage's rollback commands, count the failure
                    towards the circuit breaker, then escalate
  close             incident mitigated: alert, open the maintenance ticket, keep assets muted
  escalate          anything that could not run or verify: alert a human, keep assets locked

Tables
  Incidents  pk id, sk "A" (summary) or "L#<time>#<n>" (one item per step: the audit trail)
  Guardrails pk key: "rate#<asset>" {acts: {incident: time}} automated actions in the last hour;
             "breaker#<asset>" {failures, open_until} failed verifications (circuit breaker)
  Locks      pk asset: {incident_id, role, expires_at}. A conditional write is the lock, so two
             playbooks never command the same asset. Roles:
               target / source / commanded  any event on the asset joins the holding incident
               affected                     (expected side effects) only unexplained events join;
                                            a diagnosed fault there opens its own incident
"""
from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common.topology import GATEWAYS, downstream, gateway_of
from playbooks.catalog import PlanError, build_plan, evaluate_stage

POLL_S = int(os.environ.get("POLL_S", "10"))
LOCK_S = int(os.environ.get("LOCK_S", "7200"))       # how long an incident holds its assets at most
MUTE_S = int(os.environ.get("MUTE_S", "3600"))       # after closing: events on its assets join it
FRESH_S = int(os.environ.get("FRESH_S", "120"))      # telemetry older than this is not trusted
AUTOMATION = os.environ.get("AUTOMATION", "on")      # "on", or "notify" (alert-only mode M1)
MAX_ACTIONS_PER_HOUR = int(os.environ.get("MAX_ACTIONS_PER_HOUR", "3"))   # per asset, automated incidents
BREAKER_FAILURES = int(os.environ.get("BREAKER_FAILURES", "2"))  # failed verifications that open the breaker
BREAKER_S = int(os.environ.get("BREAKER_S", "86400"))            # how long an open breaker blocks automation
APPROVAL_TIMEOUT_S = int(os.environ.get("APPROVAL_TIMEOUT_S", "1800"))
APPROVAL_URL = os.environ.get("APPROVAL_URL", "")
RATE_WINDOW_S = 3600

DDB = boto3.resource("dynamodb")
INCIDENTS = DDB.Table(os.environ["INCIDENTS_TABLE"])
LOCKS = DDB.Table(os.environ["LOCKS_TABLE"])
TELEMETRY = DDB.Table(os.environ["TELEMETRY_TABLE"])
GUARDRAILS = DDB.Table(os.environ["GUARDRAILS_TABLE"]) if os.environ.get("GUARDRAILS_TABLE") else None
SNS = boto3.client("sns")
ALERTS_TOPIC = os.environ.get("ALERTS_TOPIC", "")
SHADOW_TRANSPORT = os.environ.get("SHADOW_TRANSPORT", "iot")
SQS = boto3.client("sqs") if SHADOW_TRANSPORT == "sqs" else None
_iot = None


def now() -> float:
    """Wall clock (replaced in offline experiments)."""
    return time.time()


def iso(t: float | None = None) -> str:
    t = now() if t is None else t
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_ddb(value):
    return json.loads(json.dumps(value), parse_float=Decimal)


def plain(value):
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


# ---------------------------------------------------------------------------------------- telemetry
def latest(gw: str, n: int = 1) -> list[dict]:
    resp = TELEMETRY.query(KeyConditionExpression=Key("gw").eq(gw), ScanIndexForward=False, Limit=n)
    return [plain(i) for i in resp.get("Items", [])]


def snapshot() -> dict:
    """Newest message of every gateway that reported recently."""
    snap = {}
    for gw in GATEWAYS:
        msgs = latest(gw)
        if not msgs:
            continue
        received = msgs[0].get("received_at")
        if received and now() - datetime.fromisoformat(received.replace("Z", "+00:00")).timestamp() > FRESH_S:
            continue
        snap[gw] = msgs[0]
    return snap


# ---------------------------------------------------------------------------------------- incidents
_log_n = 0


def log(incident_id: str, step: str, **detail) -> None:
    global _log_n
    _log_n += 1
    INCIDENTS.put_item(Item=to_ddb({"id": incident_id, "sk": f"L#{iso()}#{_log_n:05d}", "step": step,
                                    "at": iso(), **detail}))


def update(incident_id: str, **fields) -> None:
    fields["updated_at"] = iso()
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in to_ddb(fields).items()}
    INCIDENTS.update_item(Key={"id": incident_id, "sk": "A"},
                          UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                          ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def alert(subject: str, body: dict) -> None:
    if ALERTS_TOPIC:
        SNS.publish(TopicArn=ALERTS_TOPIC, Subject=subject[:100], Message=json.dumps(body, indent=2, default=str))


# ---------------------------------------------------------------------------------------- locks
WEAK_ROLES = ("affected", "notified")


def acquire(asset: str, incident_id: str, role: str, seconds: int, takeover: bool = False) -> bool:
    """Conditional write = lock. `takeover` also wins over weak locks (side effects, notify-only)."""
    t = int(now())
    cond = "attribute_not_exists(asset) OR expires_at < :now OR incident_id = :id"
    values = {":now": t, ":id": incident_id}
    names = {}
    if takeover:
        cond += " OR #r IN (:w0, :w1)"
        names = {"#r": "role"}
        values.update({":w0": WEAK_ROLES[0], ":w1": WEAK_ROLES[1]})
    try:
        LOCKS.put_item(Item={"asset": asset, "incident_id": incident_id, "role": role, "expires_at": t + seconds,
                             "ttl": t + seconds + 86400},
                       ConditionExpression=cond, ExpressionAttributeValues=values,
                       **({"ExpressionAttributeNames": names} if names else {}))
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def transfer(old: str, new: str) -> int:
    """Move an incident's locks to another incident (a diagnosed fault supersedes a notify-only one)."""
    moved = 0
    for item in LOCKS.scan(FilterExpression="incident_id = :id", ExpressionAttributeValues={":id": old}).get("Items", []):
        try:
            LOCKS.update_item(Key={"asset": item["asset"]}, UpdateExpression="SET incident_id = :new, #r = :r",
                              ConditionExpression="incident_id = :old", ExpressionAttributeNames={"#r": "role"},
                              ExpressionAttributeValues={":new": new, ":old": old, ":r": "affected"})
            moved += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return moved


def holders(assets: list[str]) -> list[dict]:
    keys = [{"asset": a} for a in dict.fromkeys(a for a in assets if a)]
    if not keys:
        return []
    items = DDB.batch_get_item(RequestItems={LOCKS.name: {"Keys": keys}})["Responses"].get(LOCKS.name, [])
    return [plain(i) for i in items if int(i["expires_at"]) >= int(now())]


def hold(incident_id: str, seconds: int) -> None:
    """Set the expiry of every lock this incident owns."""
    t = int(now())
    for item in LOCKS.scan(FilterExpression="incident_id = :id",
                           ExpressionAttributeValues={":id": incident_id}).get("Items", []):
        LOCKS.update_item(Key={"asset": item["asset"]}, UpdateExpression="SET expires_at = :e, #t = :ttl",
                          ConditionExpression="incident_id = :id", ExpressionAttributeNames={"#t": "ttl"},
                          ExpressionAttributeValues={":e": t + seconds, ":ttl": t + seconds + 86400,
                                                     ":id": incident_id})


# ---------------------------------------------------------------------------------------- guardrails
def guard_item(key: str) -> dict:
    if GUARDRAILS is None:
        return {}
    return plain(GUARDRAILS.get_item(Key={"key": key}).get("Item", {}))


def recent_actions(asset: str) -> dict:
    """incident -> time of automated actions on the asset within the rate window."""
    acts = guard_item(f"rate#{asset}").get("acts", {})
    return {i: t for i, t in acts.items() if t >= now() - RATE_WINDOW_S}


def record_action(asset: str, incident_id: str) -> None:
    if GUARDRAILS is None:
        return
    acts = {**recent_actions(asset), incident_id: int(now())}
    GUARDRAILS.put_item(Item={"key": f"rate#{asset}", "acts": acts, "ttl": int(now()) + RATE_WINDOW_S + 86400})


def breaker(asset: str) -> dict:
    item = guard_item(f"breaker#{asset}")
    return {**item, "open": int(item.get("open_until", 0)) > now()}


def record_failure(asset: str, incident_id: str, reason: str) -> bool:
    """Count a failed verification; returns True when this failure opens the breaker."""
    if GUARDRAILS is None:
        return False
    failures = int(guard_item(f"breaker#{asset}").get("failures", 0)) + 1
    opens = failures >= BREAKER_FAILURES
    GUARDRAILS.put_item(Item=to_ddb({"key": f"breaker#{asset}", "failures": failures, "last_incident": incident_id,
                                     "last_reason": reason[:300], "open_until": int(now()) + BREAKER_S if opens else 0,
                                     "ttl": int(now()) + BREAKER_S + 86400}))
    return opens


def record_success(asset: str) -> None:
    """Consecutive-failure breaker: a verified remediation resets the count."""
    if GUARDRAILS is not None:
        GUARDRAILS.delete_item(Key={"key": f"breaker#{asset}"})


def guardrail_block(plan: dict, incident_id: str) -> str | None:
    for asset in dict.fromkeys([plan["target"], *plan["commanded"]]):
        b = breaker(asset)
        if b["open"]:
            return (f"circuit breaker open for {asset}: {b.get('failures')} failed verifications "
                    f"(last {b.get('last_incident')}); automation disabled until {iso(b['open_until'])}")
    for asset in plan["commanded"]:
        others = {i for i in recent_actions(asset) if i != incident_id}
        if len(others) >= MAX_ACTIONS_PER_HOUR:
            return f"rate limit: {asset} already had {len(others)} automated actions in the last hour"
    return None


# ---------------------------------------------------------------------------------------- shadow
def send_shadow(gw: str, desired: dict) -> None:
    """Desired state for one gateway's device shadow (IoT Core on AWS, the bridge's queue locally)."""
    payload = {"state": {"desired": desired}}
    if SHADOW_TRANSPORT == "sqs":
        SQS.send_message(QueueUrl=os.environ["SHADOW_QUEUE_URL"], MessageBody=json.dumps({"thing": gw, "payload": payload}))
    else:
        global _iot
        if _iot is None:
            endpoint = os.environ.get("IOT_DATA_ENDPOINT")
            if not endpoint:                   # every account has its own data endpoint
                endpoint = "https://" + boto3.client("iot").describe_endpoint(
                    endpointType="iot:Data-ATS")["endpointAddress"]
            _iot = boto3.client("iot-data", endpoint_url=endpoint)
        _iot.update_thing_shadow(thingName=gw, payload=json.dumps(payload).encode())


# ---------------------------------------------------------------------------------------- steps
def op_open(state: dict) -> dict:
    event = state.get("event", state)
    s = {"event": event, "poll_s": POLL_S, "stage": 0, "polls": 0}
    automated = event["playbook"] != "notify_only" and AUTOMATION == "on"
    locks = holders([event.get("target"), event.get("asset")])
    # Strong locks (an automated incident owns the asset) absorb every event. Weak locks (expected side
    # effects, or a notify-only incident) absorb only events that would not be automated anyway.
    joining = [lk for lk in locks if lk["role"] not in WEAK_ROLES or not automated]
    if joining:
        inc = joining[0]["incident_id"]
        log(inc, "correlated", fault_type=event["fault_type"], target=event["target"], asset=event["asset"],
            event_ts=event["ts"], held_as=joining[0]["role"])
        INCIDENTS.update_item(Key={"id": inc, "sk": "A"}, UpdateExpression="ADD correlated :one",
                              ExpressionAttributeValues={":one": 1})
        return {**s, "incident_id": inc, "decision": "skip"}

    inc = f"{event['ts'][:19].replace(':', '').replace('-', '')}-{event['target']}-{uuid.uuid4().hex[:4]}"
    INCIDENTS.put_item(Item=to_ddb({
        "id": inc, "sk": "A", "status": "open", "playbook": event["playbook"], "fault_type": event["fault_type"],
        "risk": event["risk"], "target": event["target"], "asset": event["asset"], "gw": event["gw"],
        "detector": event.get("detector"), "detected_ts": event["ts"], "detected_seq": event.get("seq"),
        "opened_at": iso(), "updated_at": iso(), "correlated": 0, "automation": AUTOMATION}))
    seconds = LOCK_S if automated else MUTE_S
    if not acquire(event["target"], inc, "target" if automated else "notified", seconds, takeover=automated):
        update(inc, status="skipped", reason="target locked by a concurrent incident")
        log(inc, "skipped", reason="target locked by a concurrent incident")
        return {**s, "incident_id": inc, "decision": "skip"}
    if event["asset"] != event["target"]:
        acquire(event["asset"], inc, "source" if automated else "notified", seconds, takeover=automated)
    scope = [a for a in downstream(event["target"]) if acquire(a, inc, "affected", seconds)]
    log(inc, "opened", event=event, scope=scope)
    for old in {lk["incident_id"] for lk in locks if lk["role"] == "notified"}:
        moved = transfer(old, inc)
        update(old, status="superseded", superseded_by=inc)
        log(old, "superseded", by=inc, fault_type=event["fault_type"], locks_moved=moved)
        log(inc, "supersedes", incident=old)
    return {**s, "incident_id": inc, "decision": "precheck" if automated else "notify"}


def op_notify(state: dict) -> dict:
    inc, event = state["incident_id"], state["event"]
    reason = "no automated playbook" if event["playbook"] == "notify_only" else "automation disabled (alert-only mode)"
    alert(f"[dc-selfheal] {event['fault_type']} on {event['target']}", {"incident": inc, "reason": reason, "event": event})
    update(inc, status="notified", reason=reason, closed_at=iso())
    log(inc, "notified", reason=reason)
    hold(inc, MUTE_S)
    return {**state, "decision": "done"}


def op_precheck(state: dict) -> dict:
    inc, event = state["incident_id"], state["event"]
    try:
        plan = build_plan(event, snapshot())
    except PlanError as exc:
        log(inc, "precheck_failed", reason=str(exc))
        return {**state, "decision": "escalate", "reason": f"precheck: {exc}"}
    blocked = guardrail_block(plan, inc)
    if blocked:
        log(inc, "guardrail_blocked", reason=blocked)
        return {**state, "plan": plan, "decision": "escalate", "reason": f"guardrail: {blocked}"}
    for asset in plan["commanded"]:
        if not acquire(asset, inc, "commanded", LOCK_S, takeover=True):
            other = holders([asset])
            reason = f"precheck: {asset} is held by incident {other[0]['incident_id'] if other else '?'}"
            log(inc, "precheck_failed", reason=reason)
            return {**state, "plan": plan, "decision": "escalate", "reason": reason}
    for asset in plan["affected"]:
        acquire(asset, inc, "affected", LOCK_S)                  # best effort: mutes side effects
    approved = (state.get("approval") or {}).get("decision") == "approved"
    decision = "approval" if plan["risk"] == "high" and not approved else "act"
    update(inc, status="planned", plan=plan)
    log(inc, "rechecked_after_approval" if approved else "precheck_passed", commanded=plan["commanded"],
        stages=[st["name"] for st in plan["stages"]], next=decision)
    return {**state, "plan": plan, "decision": decision}


def op_request_approval(state: dict) -> dict:
    """Runs inside the .waitForTaskToken task: the execution now waits for the approval Lambda."""
    inc, plan = state["incident_id"], state["plan"]
    token = state["_task_token"]
    nonce = secrets.token_urlsafe(24)                      # one-time secret in the approval link
    INCIDENTS.put_item(Item={"id": inc, "sk": "APPROVAL", "token": token, "nonce": nonce, "status": "pending",
                             "requested_at": iso(), "expires_at": int(now()) + APPROVAL_TIMEOUT_S})
    link = f"{APPROVAL_URL.rstrip('/')}/?incident={inc}&nonce={nonce}" if APPROVAL_URL else None
    alert(f"[dc-selfheal] APPROVAL NEEDED: {plan['playbook']} on {plan['target']}", {
        "incident": inc, "risk": plan["risk"], "open_to_approve_or_reject": link,
        "expires_in_minutes": APPROVAL_TIMEOUT_S // 60,
        "stages": [{"name": st["name"], "commands": st["commands"]} for st in plan["stages"]],
        "ticket": plan.get("ticket")})
    update(inc, status="awaiting_approval", approval_requested_at=iso())
    log(inc, "approval_requested", expires_in_s=APPROVAL_TIMEOUT_S, link_sent=bool(link))
    return {"requested": True}


def op_reject(state: dict) -> dict:
    inc, approval = state["incident_id"], state.get("approval") or {}
    reason = f"plan rejected by {approval.get('by', 'operator')}"
    update(inc, status="rejected", reason=reason, closed_at=iso())
    log(inc, "rejected", by=approval.get("by"), at=approval.get("at"))
    alert(f"[dc-selfheal] Rejected: {state['plan']['playbook']} on {state['plan']['target']}",
          {"incident": inc, "reason": reason})
    hold(inc, MUTE_S)                                        # nothing was sent; keep related events together
    return {**state, "decision": "done"}


def op_act(state: dict) -> dict:
    inc, plan, k = state["incident_id"], state["plan"], int(state["stage"])
    stg = plan["stages"][k]
    by_gw: dict[str, dict] = {}
    for asset, desired in stg["commands"].items():
        by_gw.setdefault(gateway_of(asset), {})[asset] = desired
    gws = sorted(set(by_gw) | {c["gw"] for c in stg["checks"]})
    acted_seq = {gw: int(m[0]["seq"]) if (m := latest(gw)) else 0 for gw in gws}   # before sending
    cmd_ids = {}
    for gw, desired in by_gw.items():
        cmd_ids[gw] = f"{inc}:{k}:{gw}"
        send_shadow(gw, {**desired, "cmd_id": cmd_ids[gw], "issued_at": iso()})
    fields = {"status": "acting", "stage": k}
    if k == 0:
        fields["acted_at"] = iso()
        for asset in plan["commanded"]:
            record_action(asset, inc)                        # counts towards the per-asset rate limit
    update(inc, **fields)
    log(inc, "act", stage=k, name=stg["name"], commands=stg["commands"], cmd_ids=cmd_ids, acted_seq=acted_seq)
    return {**state, "acted_seq": acted_seq, "acted_at": iso(), "polls": 0, "decision": "wait"}


def op_verify(state: dict) -> dict:
    inc, plan, k = state["incident_id"], state["plan"], int(state["stage"])
    stg = plan["stages"][k]
    gws = {c["gw"] for c in stg["checks"]}
    recent = {gw: latest(gw, max(stg["stable"], 1)) for gw in gws}
    result = evaluate_stage(stg, recent, state["acted_seq"])
    s = {**state, "polls": int(state.get("polls", 0)) + 1, "verify": {k2: v for k2, v in result.items() if k2 != "failing"}}
    newest_ts = max((m[0]["ts"] for m in recent.values() if m), default=None)
    if result["status"] == "passed":
        log(inc, "verified", stage=k, name=stg["name"], messages_after_act=result["since"], telemetry_ts=newest_ts)
        if k + 1 < len(plan["stages"]):
            return {**s, "stage": k + 1, "decision": "next_stage"}
        update(inc, status="verified", verified_ts=newest_ts, verified_at=iso())
        record_success(plan["target"])
        return {**s, "verified_ts": newest_ts, "decision": "passed"}
    if result["status"] == "failed":
        reason = f"stage '{stg['name']}' not verified after {result['since']} messages; failing: " + ", ".join(
            f"{c['asset']}.{c['signal']} {c['op']} {c['value']}" for c in result["failing"])
        log(inc, "verify_failed", stage=k, reason=reason, telemetry_ts=newest_ts)
        return {**s, "decision": "failed", "reason": reason}
    return {**s, "decision": "pending"}


def op_rollback(state: dict) -> dict:
    """The stage did not verify: undo it (or hold, when undoing is less safe), count the failure."""
    inc, plan, k = state["incident_id"], state["plan"], int(state["stage"])
    stg = plan["stages"][k]
    commands = stg.get("rollback") or {}
    by_gw: dict[str, dict] = {}
    for asset, desired in commands.items():
        by_gw.setdefault(gateway_of(asset), {})[asset] = desired
    for gw, desired in by_gw.items():
        send_shadow(gw, {**desired, "cmd_id": f"{inc}:{k}:rollback:{gw}", "issued_at": iso()})
    note = stg.get("rollback_note") or ("rolled back" if commands else "held")
    log(inc, "rolled_back" if commands else "rollback_hold", stage=k, commands=commands, note=note)
    opened = record_failure(plan["target"], inc, state.get("reason", ""))
    if opened:
        log(inc, "circuit_breaker_opened", asset=plan["target"], failures=BREAKER_FAILURES)
    update(inc, rolled_back=bool(commands))
    reason = f"{state.get('reason', 'verification failed')}; {'rolled back' if commands else 'held'}: {note}"
    if opened:
        reason += f"; circuit breaker opened for {plan['target']}"
    return {**state, "decision": "escalate", "reason": reason}


def op_close(state: dict) -> dict:
    inc, plan = state["incident_id"], state["plan"]
    update(inc, status="mitigated", closed_at=iso())
    log(inc, "closed", ticket=plan.get("ticket"))
    alert(f"[dc-selfheal] Mitigated: {plan['playbook']} on {plan['target']}",
          {"incident": inc, "ticket": plan.get("ticket"), "verified_ts": state.get("verified_ts")})
    hold(inc, MUTE_S)
    return {**state, "decision": "done"}


def op_escalate(state: dict) -> dict:
    inc = state.get("incident_id")
    err = state.get("error")
    if err and err.get("Error") == "States.Timeout" and inc:
        reason = f"approval timed out after {APPROVAL_TIMEOUT_S // 60} min; nothing was sent"
        try:
            INCIDENTS.update_item(Key={"id": inc, "sk": "APPROVAL"}, UpdateExpression="SET #s = :x",
                                  ConditionExpression="#s = :p", ExpressionAttributeNames={"#s": "status"},
                                  ExpressionAttributeValues={":x": "expired", ":p": "pending"})
        except ClientError:
            pass
    else:
        reason = state.get("reason") or (f"{err.get('Error')}: {str(err.get('Cause'))[:500]}" if err else "unknown")
    event = state.get("event", {})
    alert(f"[dc-selfheal] ESCALATED: {event.get('fault_type')} on {event.get('target')}",
          {"incident": inc, "reason": reason, "event": event, "plan": state.get("plan")})
    if inc:
        update(inc, status="escalated", reason=reason, closed_at=iso())
        log(inc, "escalated", reason=reason)
        hold(inc, LOCK_S)                      # no automated retry on these assets; a human takes over
    return {**state, "decision": "done", "reason": reason}


OPS = {"open": op_open, "notify": op_notify, "precheck": op_precheck, "request_approval": op_request_approval,
       "reject": op_reject, "act": op_act, "verify": op_verify, "rollback": op_rollback, "close": op_close,
       "escalate": op_escalate}


def handler(event, context):
    state = event["state"]
    if "task_token" in event:
        state = {**state, "_task_token": event["task_token"]}
    return OPS[event["op"]](state)
