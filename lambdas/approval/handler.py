"""Approval Lambda: a human approves or rejects a high-risk plan.

Reached two ways, with the same checks:
  * Lambda function URL (the link in the approval email)
      GET   shows the plan and two buttons; it never decides anything, because mail scanners
            and link previews open links automatically
      POST  (the buttons) records the decision
  * direct invoke {"incident", "nonce", "decision": "approve"|"reject", "by"} (make approve / reject)

The link carries a one-time random nonce stored with the Step Functions task token in the
Incidents table (sk "APPROVAL"). A decision is accepted once, only while the request is pending
and not expired; it resumes the waiting execution with SendTaskSuccess
{"decision": "approved"|"rejected", "by", "at"}.
"""
from __future__ import annotations

import base64
import hmac
import html
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

import boto3
from botocore.exceptions import ClientError

INCIDENTS = boto3.resource("dynamodb").Table(os.environ["INCIDENTS_TABLE"])
SFN = boto3.client("stepfunctions")
DECISIONS = {"approve": "approved", "reject": "rejected"}


def now() -> float:
    return time.time()


def iso() -> str:
    return datetime.fromtimestamp(now(), timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pending(incident: str, nonce: str) -> tuple[dict | None, int, str]:
    item = INCIDENTS.get_item(Key={"id": incident, "sk": "APPROVAL"}).get("Item") if incident else None
    if not item or not nonce or not hmac.compare_digest(str(item.get("nonce", "")), nonce):
        return None, 403, "This approval link is not valid."
    if item["status"] != "pending":
        return None, 409, f"This request was already handled ({item['status']})."
    if now() > int(item["expires_at"]):
        return None, 410, "This approval request has expired; the incident was escalated."
    return item, 200, ""


def decide(incident: str, nonce: str, decision: str, by: str) -> tuple[int, str]:
    if decision not in DECISIONS:
        return 400, "decision must be approve or reject"
    item, code, message = pending(incident, nonce)
    if item is None:
        return code, message
    result = DECISIONS[decision]
    try:
        INCIDENTS.update_item(
            Key={"id": incident, "sk": "APPROVAL"},
            UpdateExpression="SET #s = :d, decided_by = :by, decided_at = :at",
            ConditionExpression="#s = :p AND nonce = :n",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":d": result, ":by": by, ":at": iso(), ":p": "pending", ":n": nonce})
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return 409, "This request was already handled."
        raise
    try:
        SFN.send_task_success(taskToken=item["token"],
                              output=json.dumps({"decision": result, "by": by, "at": iso()}))
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("TaskTimedOut", "TaskDoesNotExist", "InvalidToken"):
            INCIDENTS.update_item(Key={"id": incident, "sk": "APPROVAL"}, UpdateExpression="SET #s = :x",
                                  ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":x": "expired"})
            return 410, "The playbook stopped waiting (timed out); the incident was escalated."
        raise
    return 200, f"Plan {result} by {by}."


# ---------------------------------------------------------------------------------------- web page
def page(title: str, body: str, code: int = 200) -> dict:
    doc = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
           f"<title>{html.escape(title)}</title><style>body{{font-family:system-ui,sans-serif;max-width:40rem;"
           f"margin:2rem auto;padding:0 1rem;line-height:1.5}}button{{font-size:1rem;padding:.5rem 1.2rem;"
           f"margin-right:.5rem}}code{{background:#eee;padding:0 .2rem}}</style></head><body>"
           f"<h1>{html.escape(title)}</h1>{body}</body></html>")
    return {"statusCode": code, "headers": {"content-type": "text/html; charset=utf-8"}, "body": doc}


def confirm_page(incident: str, nonce: str) -> dict:
    item, code, message = pending(incident, nonce)
    if item is None:
        return page("Approval", f"<p>{html.escape(message)}</p>", code)
    summary = INCIDENTS.get_item(Key={"id": incident, "sk": "A"}).get("Item", {})
    plan = summary.get("plan", {})
    stages = "".join(f"<li>{html.escape(st['name'])}: <code>{html.escape(json.dumps(st['commands'], default=str))}"
                     f"</code></li>" for st in plan.get("stages", []))
    esc = html.escape
    body = (f"<p><b>{esc(str(summary.get('fault_type')))}</b> on <b>{esc(str(summary.get('target')))}</b>, "
            f"risk <b>{esc(str(plan.get('risk')))}</b>, playbook <code>{esc(str(plan.get('playbook')))}</code>.</p>"
            f"<ol>{stages}</ol><p>{esc(str(plan.get('ticket', '')))}</p>"
            f"<form method='post'><input type='hidden' name='incident' value='{esc(incident)}'>"
            f"<input type='hidden' name='nonce' value='{esc(nonce)}'>"
            f"<p><label>Your name <input name='by' required></label></p>"
            f"<button name='decision' value='approve'>Approve</button>"
            f"<button name='decision' value='reject'>Reject</button></form>")
    return page(f"Approve remediation for {summary.get('target')}?", body)


def handler(event, context):
    if "requestContext" not in event:                      # direct invoke (make approve / reject)
        code, message = decide(event.get("incident", ""), event.get("nonce", ""), event.get("decision", ""),
                               event.get("by", "operator"))
        return {"status": code, "message": message}
    method = event["requestContext"].get("http", {}).get("method", "GET")
    if method == "POST":
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        form = {k: v[0] for k, v in parse_qs(raw).items()}
        code, message = decide(form.get("incident", ""), form.get("nonce", ""), form.get("decision", ""),
                               (form.get("by") or "operator").strip()[:60])
        return page("Approval", f"<p>{html.escape(message)}</p>", code)
    q = event.get("queryStringParameters") or {}
    return confirm_page(q.get("incident", ""), q.get("nonce", ""))
