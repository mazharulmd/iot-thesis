"""A small Amazon States Language interpreter for offline runs and tests.

It executes the subset the remediation definition uses (Task with Parameters, Retry and Catch,
including the lambda:invoke.waitForTaskToken integration and $$.Task.Token; Choice with
StringEquals; Wait with Seconds/SecondsPath; Succeed; Fail), so the exact definition that is
deployed can be run against the real Lambda code without Step Functions.

An execution is a generator. It yields
    ("wait", seconds)                      at every Wait state, and
    ("token", token, timeout_seconds)      when a task waits for a task token.
The caller resumes a token wait with gen.send(reply), where reply is ("success", output),
("failure", error, cause) or ("timeout",). The generator returns (status, output, history).
"""
from __future__ import annotations

import copy
import uuid
from typing import Callable, Generator


class ExecutionFailed(Exception):
    pass


class TaskFailed(Exception):
    def __init__(self, error: str, cause: str = ""):
        super().__init__(f"{error}: {cause}")
        self.error, self.cause = error, cause


def get_path(data, path: str):
    if path == "$":
        return data
    if not path.startswith("$."):
        raise ValueError(f"unsupported path {path}")
    for part in path[2:].split("."):
        data = data[part]
    return data


def set_path(data: dict, path: str, value) -> dict:
    if path == "$":
        return value
    out = copy.deepcopy(data)
    node = out
    parts = path[2:].split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    return out


def render(params, data, context: dict | None = None):
    if isinstance(params, dict):
        out = {}
        for k, v in params.items():
            if k.endswith(".$"):
                out[k[:-2]] = copy.deepcopy(get_path(context or {}, "$" + v[2:]) if v.startswith("$$")
                                            else get_path(data, v))
            else:
                out[k] = render(v, data, context)
        return out
    if isinstance(params, list):
        return [render(v, data, context) for v in params]
    return params


def _choice_matches(rule: dict, data) -> bool:
    try:
        value = get_path(data, rule["Variable"])
    except (KeyError, TypeError):
        return False
    if "StringEquals" in rule:
        return value == rule["StringEquals"]
    raise ValueError(f"unsupported choice rule {rule}")


def execute(definition: dict, data: dict, invoke: Callable[[str, dict], dict],
            max_steps: int = 10_000) -> Generator[tuple, None, tuple]:
    """invoke(resource, payload) -> result, raising an exception for a task error."""
    states = definition["States"]
    name = definition["StartAt"]
    history = []
    for _ in range(max_steps):
        st = states[name]
        history.append(name)
        kind = st["Type"]
        if kind == "Task":
            resource = st["Resource"]
            token = uuid.uuid4().hex if resource.endswith(".waitForTaskToken") else None
            context = {"Task": {"Token": token}}
            payload = render(st.get("Parameters", {}), data, context) if "Parameters" in st else data
            try:
                if resource.startswith("arn:aws:states:::lambda:invoke"):
                    result = invoke(payload["FunctionName"], payload.get("Payload", {}))
                    if token:
                        reply = yield ("token", token, st.get("TimeoutSeconds"))
                        if reply[0] == "success":
                            result = reply[1]
                        elif reply[0] == "timeout":
                            raise TaskFailed("States.Timeout", "task token was not returned in time")
                        else:
                            raise TaskFailed(reply[1], reply[2] if len(reply) > 2 else "")
                    else:
                        result = {"Payload": result}
                else:
                    result = invoke(resource, payload)
            except Exception as exc:  # noqa: BLE001 - mapped to States.ALL like Step Functions
                error = exc.error if isinstance(exc, TaskFailed) else type(exc).__name__
                cause = exc.cause if isinstance(exc, TaskFailed) else str(exc)
                catch = next((c for c in st.get("Catch", []) if "States.ALL" in c["ErrorEquals"]
                              or error in c["ErrorEquals"]), None)
                if catch is None:
                    return "FAILED", {"Error": error, "Cause": cause}, history
                data = set_path(data, catch.get("ResultPath", "$"), {"Error": error, "Cause": cause})
                name = catch["Next"]
                continue
            data = set_path(data, st.get("ResultPath", "$"), result)
            name = st["Next"]
        elif kind == "Choice":
            name = next((r["Next"] for r in st["Choices"] if _choice_matches(r, data)), st.get("Default"))
            if name is None:
                return "FAILED", {"Error": "States.NoChoiceMatched"}, history
        elif kind == "Wait":
            seconds = st["Seconds"] if "Seconds" in st else get_path(data, st["SecondsPath"])
            yield ("wait", float(seconds))
            name = st["Next"]
        elif kind == "Pass":
            data = set_path(data, st.get("ResultPath", "$"), st.get("Result", data))
            name = st["Next"]
        elif kind == "Succeed":
            return "SUCCEEDED", data, history
        elif kind == "Fail":
            return "FAILED", {"Error": st.get("Error"), "Cause": st.get("Cause")}, history
        else:
            raise ValueError(f"unsupported state type {kind}")
    raise ExecutionFailed("too many steps")
