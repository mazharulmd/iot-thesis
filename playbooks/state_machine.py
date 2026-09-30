"""The remediation state machine (Amazon States Language), shared by every playbook.

    Open ──skip──────────────────────────────────────────► Correlated   (event joins an open incident)
      │  └─notify──► Notify ────────────────────────────► Notified     (no automated playbook)
      ▼
    Precheck ──escalate (unsafe, busy, rate limit, circuit breaker open)──► Escalate
      │  └─approval──► RequestApproval ══ waits for a human (task token) ══╗
      │                    ├─ approved ──► Precheck again (fresh telemetry) ║ timeout ──► Escalate
      │                    └─ rejected ──► Reject ──► Rejected              ║
      ▼
    Act ──► WaitForEffect ──► Verify ──pending──► WaitForEffect
      ▲                         ├─next_stage──► Act
      │                         ├─passed──────► Close ──► Mitigated
      └─────────────────────────┴─failed──────► Rollback ──► Escalate ──► Escalated (Fail)

Every task calls the remediation Lambda with {"op": <step>, "state": <whole state>} and gets the
new state back, so the state machine holds no playbook logic. Any task error goes to Escalate.
RequestApproval uses the `.waitForTaskToken` integration: the Lambda stores the token and alerts
a human; the approval Lambda (behind a function URL) returns the decision with SendTaskSuccess.
"""
from __future__ import annotations

import json

LAMBDA_ERRORS = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException",
                 "Lambda.TooManyRequestsException"]


def _task(op: str, next_state: str, fn: str, catch: bool = True) -> dict:
    t = {
        "Type": "Task",
        "Resource": fn,
        "Parameters": {"op": op, "state.$": "$"},
        "Retry": [{"ErrorEquals": LAMBDA_ERRORS, "IntervalSeconds": 2, "MaxAttempts": 3, "BackoffRate": 2.0}],
        "Next": next_state,
    }
    if catch:
        t["Catch"] = [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Escalate"}]
    return t


def _choice(branches: dict, default: str) -> dict:
    return {"Type": "Choice",
            "Choices": [{"Variable": "$.decision", "StringEquals": k, "Next": v} for k, v in branches.items()],
            "Default": default}


def _approval(fn: str, timeout_s: int) -> dict:
    return {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
        "Parameters": {"FunctionName": fn,
                       "Payload": {"op": "request_approval", "state.$": "$", "task_token.$": "$$.Task.Token"}},
        "TimeoutSeconds": timeout_s,
        "ResultPath": "$.approval",
        "Retry": [{"ErrorEquals": LAMBDA_ERRORS, "IntervalSeconds": 2, "MaxAttempts": 3, "BackoffRate": 2.0}],
        "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Escalate"}],
        "Next": "AfterApproval",
    }


def definition(fn: str = "${RemediationFunctionArn}", approval_timeout_s: int = 1800) -> dict:
    return {
        "Comment": "dc-selfheal remediation: lock, precheck, risk tier, act via shadow, verify, close or escalate",
        "StartAt": "Open",
        "States": {
            "Open": _task("open", "AfterOpen", fn),
            "AfterOpen": _choice({"skip": "Correlated", "notify": "Notify"}, "Precheck"),
            "Notify": _task("notify", "Notified", fn),
            "Precheck": _task("precheck", "AfterPrecheck", fn),
            "AfterPrecheck": _choice({"escalate": "Escalate", "approval": "RequestApproval"}, "Act"),
            "RequestApproval": _approval(fn, approval_timeout_s),
            "AfterApproval": {"Type": "Choice", "Choices": [
                {"Variable": "$.approval.decision", "StringEquals": "approved", "Next": "Precheck"}],
                "Default": "Reject"},
            "Reject": _task("reject", "Rejected", fn),
            "Act": _task("act", "WaitForEffect", fn),
            "WaitForEffect": {"Type": "Wait", "SecondsPath": "$.poll_s", "Next": "Verify"},
            "Verify": _task("verify", "AfterVerify", fn),
            "AfterVerify": _choice({"pending": "WaitForEffect", "next_stage": "Act", "passed": "Close"}, "Rollback"),
            "Rollback": _task("rollback", "Escalate", fn),
            "Close": _task("close", "Mitigated", fn),
            "Escalate": _task("escalate", "Escalated", fn, catch=False),
            "Correlated": {"Type": "Succeed"},
            "Notified": {"Type": "Succeed"},
            "Rejected": {"Type": "Succeed"},
            "Mitigated": {"Type": "Succeed"},
            "Escalated": {"Type": "Fail", "Error": "RemediationEscalated",
                          "Cause": "The playbook could not run or did not verify; a human was notified."},
        },
    }


def definition_json(fn: str = "${RemediationFunctionArn}", approval_timeout_s: int = 1800) -> str:
    return json.dumps(definition(fn, approval_timeout_s), indent=2)
