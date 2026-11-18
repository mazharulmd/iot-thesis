"""The dashboard's view of the system: one JSON snapshot built from telemetry, anomalies and incidents.

Both sources (the offline simulation and a deployed stack) feed the same LiveState, so the page
looks the same whether it runs on a laptop or against AWS.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from common.topology import GATEWAYS

HISTORY = 360                       # points kept per series (one per gateway message, 1 h at 10 s)
INLET_LIMIT_C = 27.0

# Incident steps shown on the timeline, in order. The rest of the audit trail is listed as text.
TIMELINE = ["opened", "approval_requested", "act", "verified", "closed"]
FINAL = {"mitigated": "mitigated", "escalated": "escalated", "notified": "notified", "rejected": "rejected",
         "skipped": "skipped", "superseded": "superseded"}


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return v


def series_point(gateways: dict) -> dict:
    """Key values for the trend charts from the latest message of every gateway."""
    p = {}
    for z in range(1, 5):
        assets = gateways.get(f"zone{z}", {}).get("assets", {})
        inlets = [a.get("t_in") for k, a in assets.items() if k.startswith("rack") and a.get("t_in") is not None]
        if inlets:
            p[f"zone{z}_inlet"] = round(max(float(v) for v in inlets), 2)
        pdu = assets.get(f"pdu{z}", {})
        if "load_pct" in pdu:
            p[f"pdu{z}_load"] = _num(pdu["load_pct"])
    plant = gateways.get("plant", {}).get("assets", {})
    if "chiller" in plant:
        p["chw_sup"] = _num(plant["chiller"].get("t_sup"))
        p["chw_sp"] = _num(plant["chiller"].get("sp"))
    pumps = [plant.get(k, {}) for k in ("pump1", "pump2")]
    if any(pumps):
        p["flow"] = round(sum(float(x.get("flow_lps") or 0) for x in pumps), 2)
        running = [float(x.get("vib_mms") or 0) for x in pumps if x.get("status") == "on"]
        p["vib"] = round(max(running), 2) if running else 0.0
    for u in ("ups1", "ups2"):
        if u in plant:
            p[f"{u}_batt"] = _num(plant[u].get("t_batt"))
    return p


class LiveState:
    """Thread-safe state behind /api/state."""

    def __init__(self, mode: str, **info):
        self.lock = threading.Lock()
        self.mode = mode
        self.info = dict(info)
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.gateways: dict = {}
            self.history: deque = deque(maxlen=HISTORY)
            self.events: deque = deque(maxlen=60)
            self.incidents: list = []
            self.approvals: list = []
            self.alerts: deque = deque(maxlen=40)
            self.commands: deque = deque(maxlen=40)
            self.faults: list = []
            self.counters = {"messages": 0, "anomalies": 0, "commands": 0}
            self.clock = {"t": 0.0, "label": ""}
            self.latency_ms = None
            self.error = ""

    # ---- updates from a source -------------------------------------------------------------
    def message(self, msg: dict, t: float) -> None:
        with self.lock:
            prev = self.gateways.get(msg["gw"])
            if prev and prev.get("seq") == msg.get("seq"):
                return
            self.gateways[msg["gw"]] = {"ts": msg.get("ts"), "seq": msg.get("seq"), "t": t,
                                        "assets": {a: {k: _num(v) for k, v in vals.items()} if isinstance(vals, dict)
                                                   else vals for a, vals in msg.get("assets", {}).items()},
                                        "quarantined": msg.get("quarantined") or msg.get("assets", {}).get(
                                            "quarantined", [])}
            self.counters["messages"] += 1
            if msg["gw"] == "plant" or len(self.gateways) == len(GATEWAYS):
                self.history.append({"t": t, **series_point(self.gateways)})

    def set_clock(self, t: float, label: str) -> None:
        with self.lock:
            self.clock = {"t": t, "label": label}

    def add_event(self, e: dict) -> None:
        with self.lock:
            self.events.appendleft({k: e.get(k) for k in ("t", "ts", "fault_type", "target", "asset", "gw", "risk",
                                                           "playbook", "score")})
            self.counters["anomalies"] += 1

    def add_command(self, c: dict) -> None:
        with self.lock:
            self.commands.appendleft(c)
            self.counters["commands"] += 1

    def add_alert(self, a: dict) -> None:
        with self.lock:
            self.alerts.appendleft(a)

    def set_incidents(self, incidents: list[dict], approvals: list[dict]) -> None:
        with self.lock:
            self.incidents, self.approvals = incidents, approvals

    def set_commands(self, commands: list[dict]) -> None:
        with self.lock:
            self.commands = deque(commands[:40], maxlen=40)
            self.counters["commands"] = len(commands)

    def set_alerts(self, alerts: list[dict]) -> None:
        with self.lock:
            self.alerts = deque(alerts[:40], maxlen=40)

    def set_faults(self, faults: list[dict]) -> None:
        with self.lock:
            self.faults = faults

    # ---- the snapshot ----------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self.lock:
            incs = self.incidents
            status = [i["status"] for i in incs]
            kpis = {
                **self.counters,
                "incidents": len(incs),
                "mitigated": status.count("mitigated"),
                "escalated": status.count("escalated"),
                "active": sum(s in ("open", "planned", "acting", "verified", "awaiting_approval") for s in status),
                "awaiting": len(self.approvals),
                "alerts": len(self.alerts),
            }
            mttr = [i["recovery_s"] for i in incs if i.get("recovery_s") is not None]
            kpis["median_recovery_s"] = sorted(mttr)[len(mttr) // 2] if mttr else None
            hot = [a.get("t_in") for g in self.gateways.values() for k, a in g["assets"].items()
                   if k.startswith("rack") and isinstance(a, dict) and a.get("t_in") is not None]
            kpis["hottest_inlet_c"] = max(hot) if hot else None
            kpis["racks_over_limit"] = sum(1 for v in hot if v > INLET_LIMIT_C)
            if self.latency_ms is not None:
                kpis["latency_ms"] = self.latency_ms
            return {
                "mode": self.mode, "info": self.info, "clock": self.clock, "server_time": time.time(),
                "gateways": self.gateways, "history": list(self.history), "events": list(self.events),
                "incidents": incs, "approvals": self.approvals, "alerts": list(self.alerts),
                "commands": list(self.commands), "faults": self.faults, "kpis": kpis, "error": self.error,
                "limit_c": INLET_LIMIT_C,
            }


# Audit-trail steps after which the remediation Lambda sends an email to the operators
ALERT_STEPS = {"notified": "Alert", "approval_requested": "Approval needed", "rejected": "Rejected",
               "closed": "Mitigated", "escalated": "Escalated"}


def alerts_from(views: list[dict]) -> list[dict]:
    out = []
    for v in views:
        for e in v["trail"]:
            if e["step"] in ALERT_STEPS:
                out.append({"at": e["at"], "subject": f"{ALERT_STEPS[e['step']]}: {v['fault_type']} on {v['target']}",
                            "kind": e["step"]})
    return sorted(out, key=lambda a: a["at"] or "", reverse=True)


def incident_view(summary: dict, log: list[dict], t_of=None) -> dict:
    """One incident card: summary fields, the timeline steps reached, and the audit trail."""
    steps = {}
    for entry in log:
        name = entry.get("step")
        if name in ("rechecked_after_approval",):
            name = "approval_requested"
        if name in TIMELINE and name not in steps:
            steps[name] = entry.get("at")
        if name in ("precheck_failed", "guardrail_blocked", "verify_failed", "rolled_back", "rejected",
                    "escalated", "circuit_breaker_opened"):
            steps.setdefault("problem", entry.get("at"))
    status = summary.get("status", "open")
    view = {
        "id": summary.get("id"), "fault_type": summary.get("fault_type"), "target": summary.get("target"),
        "risk": summary.get("risk"), "playbook": summary.get("playbook"), "status": status,
        "opened_at": summary.get("opened_at"), "closed_at": summary.get("closed_at"),
        "correlated": summary.get("correlated", 0), "reason": summary.get("reason", ""),
        "steps": steps, "final": FINAL.get(status),
        "trail": [{"at": e.get("at"), "step": e.get("step")} for e in log][-14:],
    }
    if t_of and summary.get("opened_at") and summary.get("closed_at") and status == "mitigated":
        view["recovery_s"] = round(t_of(summary["closed_at"]) - t_of(summary["opened_at"]), 1)
    return view
