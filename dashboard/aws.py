"""Live view of a deployed stack (real AWS or LocalStack): polls the DynamoDB tables.

Reads only what the pipeline already writes: the latest telemetry message of each gateway, the
Detections table (anomaly events), the Incidents table (summaries, audit trails, approvals) and the
IngestStats table (detector latency). Approvals are decided through the approval Lambda, with the same
one-time nonce checks as the email link. A poll every 3 s costs a few cents a day on demand.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Attr, Key

from common.awsenv import session, stack_outputs
from common.topology import GATEWAYS, gateway_of
from tools.incidents import plain, scan_all

from .core import LiveState, alerts_from, incident_view


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


class AwsSource:
    def __init__(self, state: LiveState, stage: str, interval_s: float = 3.0):
        self.state, self.stage, self.interval_s = state, stage, interval_s
        self.sess = session(stage)
        self.out = stack_outputs(self.sess, stage)
        ddb = self.sess.resource("dynamodb")
        self.telemetry = ddb.Table(self.out["TelemetryTableName"])
        self.incidents = ddb.Table(self.out["IncidentsTableName"])
        self.detections = ddb.Table(self.out["DetectionsTableName"]) if "DetectionsTableName" in self.out else None
        self.stats = ddb.Table(self.out["IngestStatsTableName"]) if "IngestStatsTableName" in self.out else None
        self.since = datetime.now(timezone.utc) - timedelta(hours=1)
        self._stop = threading.Event()
        self._seen_events: set = set()
        state.info.update(stage=stage, region=self.sess.region_name, menu={},
                          dashboard_url=self.out.get("DashboardUrl", ""))

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name=f"aws-{self.stage}", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def restart(self) -> None:                       # "reset view": forget what was shown so far
        self.state.reset()
        self._seen_events.clear()
        self.since = datetime.now(timezone.utc)

    def inject(self, fault_type: str) -> str:
        raise ValueError("on AWS, faults come from the simulator scenario (python -m simulator.live --scenario …)")

    def demo(self) -> str:
        raise ValueError("on AWS, run the demo scenarios with the simulator (see docs/dashboard.md)")

    def set_speed(self, speed: float) -> None:
        raise ValueError("the speed is set by the simulator on AWS")

    def set_paused(self, paused: bool) -> None:
        raise ValueError("pausing is only available in the offline simulation")

    def decide(self, incident_id: str, decision: str, by: str = "dashboard operator") -> str:
        from tools.approve import approval_item, decide
        item = approval_item(self.incidents, incident_id)
        if not item or item.get("status") != "pending":
            raise ValueError("no pending approval for this incident")
        result = decide(self.sess, self.out, incident_id, item["nonce"], decision, by)
        return f"{decision}: {str(result)[:160]}"

    # ---- polling -----------------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
                self.state.error = ""
            except Exception as exc:                 # keep polling; show the problem on the page
                self.state.error = f"{type(exc).__name__}: {exc}"[:300]
            self._stop.wait(self.interval_s)

    def poll(self) -> None:
        st = self.state
        newest = 0.0
        for gw in GATEWAYS:
            items = self.telemetry.query(KeyConditionExpression=Key("gw").eq(gw), ScanIndexForward=False,
                                         Limit=1).get("Items", [])
            if items:
                msg = plain(items[0])
                t = _epoch(msg["ts"])
                newest = max(newest, t)
                st.message(msg, t)
        if newest:
            st.set_clock(newest, datetime.fromtimestamp(newest, timezone.utc).strftime("%H:%M:%S UTC"))

        if self.detections is not None:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            items = self.detections.query(KeyConditionExpression=Key("day").eq(day), ScanIndexForward=False,
                                          Limit=200).get("Items", [])
            for e in sorted((plain(i) for i in items), key=lambda e: e["id"]):
                if e["id"] in self._seen_events or _epoch(e["ts"]) < self.since.timestamp():
                    continue
                if e.get("gw") and e["gw"] not in GATEWAYS:    # load-test virtual gateways
                    continue
                self._seen_events.add(e["id"])
                st.add_event({**e, "t": _epoch(e["ts"])})

        since = self.since.strftime("%Y-%m-%dT%H:%M:%S")
        summaries = [plain(i) for i in scan_all(self.incidents, FilterExpression=Attr("sk").eq("A"))
                     if i.get("opened_at", "") >= since]
        summaries.sort(key=lambda i: i.get("opened_at", ""), reverse=True)
        views, approvals, commands = [], [], []
        for s in summaries[:12]:
            log = [plain(i) for i in self.incidents.query(
                KeyConditionExpression=Key("id").eq(s["id"]) & Key("sk").begins_with("L#")).get("Items", [])]
            log.sort(key=lambda i: i["sk"])
            views.append(incident_view(s, log, _epoch))
            for e in log:
                if e.get("step") == "act":
                    by_gw: dict = {}
                    for asset, desired in (e.get("commands") or {}).items():
                        by_gw.setdefault(gateway_of(asset), {})[asset] = desired
                    commands += [{"t": _epoch(e["at"]), "gw": gw, "desired": d, "by": "playbook", "errors": {}}
                                 for gw, d in by_gw.items()]
            if s.get("status") == "awaiting_approval":
                plan = s.get("plan") or {}
                stages = plan.get("stages", [])
                approvals.append({"incident": s["id"], "fault_type": s.get("fault_type"), "target": s.get("target"),
                                  "risk": s.get("risk"), "playbook": s.get("playbook"),
                                  "stages": [x.get("name") for x in stages],
                                  "commands": stages[0].get("commands", {}) if stages else {},
                                  "requested_at": s.get("approval_requested_at")})
        st.set_incidents(views, approvals)
        st.set_alerts(alerts_from(views))
        st.set_commands(sorted(commands, key=lambda c: c["t"], reverse=True))

        if self.stats is not None:
            # Only the hall's own gateways: the table also keeps the load test's virtual gateways.
            items = [self.stats.get_item(Key={"gw": gw}).get("Item") or {} for gw in GATEWAYS]
            lat = [float(i["last_latency_ms"]) for i in items if "last_latency_ms" in i]
            st.latency_ms = round(sorted(lat)[len(lat) // 2], 1) if lat else None
