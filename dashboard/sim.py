"""Live simulation for the dashboard: the offline closed loop, paced to wall-clock time.

The same code as the experiments runs here (simulator, detection engine, the deployed state machine
definition, the real remediation and approval Lambda handlers against mocked AWS), but slowed down to
a chosen speed, so a fault injected from the browser can be watched while it is detected, remediated
and verified. High-risk plans wait for the person at the dashboard to approve or reject them.
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from simulator.runner import load_scenario
from simulator.config import ScenarioConfig

from .core import LiveState, alerts_from, incident_view

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "simulator" / "scenarios"

# What the injection buttons do: the fault of each scenario file (the E1 definitions), started now.
FAULT_MENU = {
    "crah_fan_failure": ("Cooling unit CRAH 2 fails", "low"),
    "rack_hotspot": ("Hotspot on rack 07", "medium"),
    "chw_supply_drift": ("Chilled water supply drifts +7 K", "medium"),
    "pump_degradation": ("Duty pump 1 wears out", "medium"),
    "sensor_stuck": ("Rack 07 inlet sensor freezes", "low"),
    "sensor_drift": ("Rack 12 inlet sensor drifts", "low"),
    "ups_battery_overheat": ("UPS 1 battery overheats", "high"),
    "pdu_overload": ("PDU 3 overloads", "high"),
}


def fault_spec(fault_type: str) -> dict:
    scn, _ = load_scenario(SCENARIOS / f"{fault_type}.yaml")
    f = next(f for f in scn.faults if f.type == fault_type)
    return {"type": f.type, "target": f.target, "severity": f.severity, "ramp_s": f.ramp_s,
            "duration_s": f.duration_s, "offset": f.offset}


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


class SimulationSource:
    def __init__(self, state: LiveState, speed: float = 10.0, detector: str = "d2h", seed: int = 7,
                 hours: float = 12.0):
        self.state = state
        self.speed = float(speed)
        self.detector = detector
        self.seed = seed
        self.hours = hours
        self.paused = False
        self.controls: queue.Queue = queue.Queue()
        self.scheduled: list = []                     # guided demo: (simulated time, fault type)
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state.info.update(menu={k: {"label": v[0], "risk": v[1]} for k, v in FAULT_MENU.items()},
                               detector=detector, speed=self.speed)

    # ---- lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._idx = {"messages": 0, "events": 0, "commands": 0}
        self._wall0, self._t0 = None, 0.0
        self.thread = threading.Thread(target=self._run, name="simulation", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.controls.put(("stop",))
        if self.thread:
            self.thread.join(timeout=30)

    def restart(self) -> None:
        self.stop()
        while not self.controls.empty():
            self.controls.get_nowait()
        self.scheduled = []
        self.state.reset()
        self.seed += 1
        self.start()

    def _run(self) -> None:
        from experiments.closed_loop import run_closed_loop
        scn = ScenarioConfig(name="dashboard", duration_s=self.hours * 3600.0, seed=self.seed)
        self.start_time = scn.start_time
        self.state.info["start_time"] = scn.start_time
        try:
            run_closed_loop(scn, detector=self.detector, observer=self)
        except Exception as exc:                                   # shown on the page
            self.state.error = f"simulation stopped: {exc!r}"

    # ---- controls from the browser -------------------------------------------------------------
    def inject(self, fault_type: str) -> str:
        if fault_type not in FAULT_MENU:
            raise ValueError(f"unknown fault {fault_type}")
        self.controls.put(("inject", fault_spec(fault_type)))
        return f"{FAULT_MENU[fault_type][0]}: injected"

    def decide(self, incident_id: str, decision: str, by: str = "dashboard operator") -> str:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        self.controls.put(("decide", incident_id, decision, by))
        return f"{decision} sent for {incident_id}"

    def demo(self) -> str:
        """A guided sequence for presentations: an abrupt fault, a slow one, then a high-risk one."""
        now = self.state.clock["t"]
        self.scheduled = [(now + 10, "crah_fan_failure"), (now + 420, "pump_degradation"),
                          (now + 900, "ups_battery_overheat")]
        return "guided demo: CRAH failure now, pump wear in 7 min, UPS overheat in 15 min (simulated)"

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.5, min(120.0, float(speed)))
        self.state.info["speed"] = self.speed
        self._wall0 = None                                          # re-anchor the pacing

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self.state.info["paused"] = self.paused
        self._wall0 = None

    # ---- called by the closed loop after every publish (every 10 simulated seconds) ----------------
    def on_publish(self, t: float, out, ddb) -> list:
        st = self.state
        for msg in out.messages[self._idx["messages"]:]:
            st.message(msg, msg["t_s"])
        self._idx["messages"] = len(out.messages)
        for e in out.events[self._idx["events"]:]:
            st.add_event({**e, "t": e.get("t_s", t)})
        self._idx["events"] = len(out.events)
        for c in out.commands[self._idx["commands"]:]:
            desired = {k: v for k, v in c["desired"].items() if k not in ("cmd_id", "issued_at")}
            st.add_command({"t": c["t_s"], "gw": c["gw"], "desired": desired,
                            "by": "operator" if str(c["desired"].get("cmd_id", "")).startswith("human") else
                            "playbook", "errors": c.get("errors") or {}})
        self._idx["commands"] = len(out.commands)
        st.set_faults([{**lab, "active": True} for lab in out.labels])
        hh, rem = divmod(int(t), 3600)
        st.set_clock(t, f"T+{hh:02d}:{rem // 60:02d}:{rem % 60:02d}")
        self._scan_incidents(ddb, t)

        # pace: simulated time advances `speed` times faster than wall-clock time
        while self.paused and not self._stop.is_set() and self.controls.empty():
            time.sleep(0.1)
        now = time.monotonic()
        if self._wall0 is None:
            self._wall0, self._t0 = now, t
        target = self._wall0 + (t - self._t0) / self.speed
        while not self._stop.is_set() and self.controls.empty() and time.monotonic() < target:
            time.sleep(min(0.05, max(0.0, target - time.monotonic())))
        cmds = []
        while self.scheduled and self.scheduled[0][0] <= t:
            cmds.append(("inject", fault_spec(self.scheduled.pop(0)[1])))
        while not self.controls.empty():
            cmds.append(self.controls.get_nowait())
        return cmds

    def _scan_incidents(self, ddb, t: float) -> None:
        items = ddb.Table("Incidents").scan()["Items"]
        from tools.incidents import plain
        items = [plain(i) for i in items]
        summaries = sorted((i for i in items if i["sk"] == "A"), key=lambda i: i.get("opened_at", ""), reverse=True)
        views, approvals = [], []
        for s in summaries[:12]:
            log = sorted((i for i in items if i["id"] == s["id"] and i["sk"].startswith("L#")), key=lambda i: i["sk"])
            views.append(incident_view(s, log, _epoch))
        for a in (i for i in items if i["sk"] == "APPROVAL" and i.get("status") == "pending"):
            s = next((x for x in summaries if x["id"] == a["id"]), {})
            plan = s.get("plan") or {}
            approvals.append({"incident": a["id"], "fault_type": s.get("fault_type"), "target": s.get("target"),
                              "risk": s.get("risk"), "playbook": s.get("playbook"),
                              "stages": [st.get("name") for st in plan.get("stages", [])],
                              "commands": plan.get("stages", [{}])[0].get("commands", {}) if plan.get("stages") else {},
                              "requested_at": s.get("approval_requested_at")})
        self.state.set_incidents(views, approvals)
        self.state.set_alerts(alerts_from(views))
