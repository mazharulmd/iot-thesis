"""Run the data hall in (scaled) real time and talk MQTT like five real gateways.

- Publishes one telemetry message per gateway every 10 simulated seconds.
- Receives commands as device-shadow deltas and reports what it applied.
- Writes ground truth (faults, commands, timings) locally; it is never published.

Examples:
    python -m simulator.live                                   # normal operation, real time
    python -m simulator.live --scenario simulator/scenarios/crah_fan_failure.yaml --speed 10
    python -m simulator.live --duration 600 --host 127.0.0.1
"""
from __future__ import annotations

import argparse
import json
import queue
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import paho.mqtt.client as mqtt

from common.topology import GATEWAYS, gateway_of, shadow_get_topic, shadow_topic, telemetry_topic

from .config import HallConfig, ScenarioConfig
from .faults import SensorLayer, apply_physical_faults
from .model import DataHall
from .runner import load_scenario

META_KEYS = {"cmd_id", "issued_at", "applied_at", "errors"}


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if hasattr(value, "item"):
        return value.item()
    return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class LiveSimulator:
    def __init__(self, scn: ScenarioConfig, cfg: HallConfig | None = None, *, host: str = "127.0.0.1",
                 port: int = 1883, speed: float = 1.0, out_dir: Path | None = None,
                 scripted_actions: bool = False, tls: dict | None = None, client_prefix: str = ""):
        self.client_prefix = client_prefix
        self.scn = scn
        self.cfg = cfg or HallConfig()
        self.host, self.port, self.tls = host, port, tls
        self.speed = speed
        self.scripted_actions = scripted_actions
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        self.out_dir = Path(out_dir or Path("runs") / f"live-{scn.name}-{stamp}")
        self.inbox: queue.Queue = queue.Queue()
        self.clients: dict[str, mqtt.Client] = {}
        self.last_version: dict[str, int] = {}
        self.commands_log: list[dict] = []
        self.truth_log: list[dict] = []         # true (noise-free) readings at each publish, for experiments
        self.messages_log: list[dict] = []
        self.published = 0
        self._stop = False

        rng = np.random.default_rng(scn.seed)
        self.hall = DataHall(self.cfg, rng)
        self.hall.t = -scn.warmup_s
        self.hall.init_load(scn.initial_busy_frac)
        self.sensors = SensorLayer(self.hall, scn.faults, np.random.default_rng(scn.seed + 10_000))

    # ------------------------------------------------------------------ MQTT
    def connect(self) -> None:
        for gw in GATEWAYS:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{self.client_prefix}{gw}",
                            protocol=mqtt.MQTTv311)
            c.user_data_set(gw)
            if self.tls:
                c.tls_set(ca_certs=self.tls["ca"], certfile=self.tls["cert"].format(gw=gw),
                          keyfile=self.tls["key"].format(gw=gw))
            c.on_connect = self._on_connect
            c.on_message = self._on_message
            c.reconnect_delay_set(1, 30)
            c.connect(self.host, self.port, keepalive=60)
            c.loop_start()
            self.clients[gw] = c
        deadline = time.time() + 10
        while time.time() < deadline and not all(c.is_connected() for c in self.clients.values()):
            time.sleep(0.1)
        if not all(c.is_connected() for c in self.clients.values()):
            raise ConnectionError(f"could not connect all gateways to MQTT at {self.host}:{self.port}")

    def _on_connect(self, client, gw, flags, reason_code, properties):
        # Runs on every (re)connect: subscribe, then ask for the shadow so that
        # commands sent while this gateway was offline are not lost.
        client.subscribe([(shadow_topic(gw, "delta"), 1), (shadow_get_topic(gw, "accepted"), 1)])
        client.publish(shadow_get_topic(gw), "{}", qos=1)

    def _on_message(self, client, gw, msg):
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        if msg.topic.endswith("/get/accepted"):
            pending = payload.get("state", {}).get("delta")
            if not pending:
                return
            payload = {"state": pending, "version": payload.get("version", 0)}
        self.inbox.put((gw, payload))

    def disconnect(self) -> None:
        for c in self.clients.values():
            c.loop_stop()
            c.disconnect()

    # ------------------------------------------------------------------ commands
    def _handle_delta(self, gw: str, delta: dict, t: float) -> None:
        version = delta.get("version", 0)
        if version and version <= self.last_version.get(gw, 0):
            return                                         # already handled
        self.last_version[gw] = version
        state = delta.get("state", {})
        received = utc_now()
        applied, errors = {}, {}
        for asset, desired in state.items():
            if asset in META_KEYS or not isinstance(desired, dict):
                continue
            try:
                if gateway_of(asset) != gw:
                    raise ValueError(f"{asset} is not connected to gateway {gw}")
                self.hall.apply_command(asset, desired)
                applied[asset] = self.hall.controls(asset)     # report the full state, not just the change
            except (ValueError, StopIteration) as exc:
                errors[asset] = str(exc)
        reported = dict(applied)
        if "cmd_id" in state:
            reported["cmd_id"] = state["cmd_id"]
        reported["applied_at"] = iso(utc_now())
        if errors:
            reported["errors"] = errors
        self.clients[gw].publish(shadow_topic(gw), json.dumps({"state": {"reported": reported}}), qos=1)
        self.commands_log.append({"gw": gw, "sim_t": round(t, 3), "received_at": iso(received),
                                  "cmd_id": state.get("cmd_id"), "issued_at": state.get("issued_at"),
                                  "applied": applied, "errors": errors})

    # ------------------------------------------------------------------ main loop
    def run(self, duration_s: float | None = None) -> Path:
        cfg = self.cfg
        while self.hall.t < 0:                              # warm-up, not real time
            self.hall.step(cfg.dt_s)
        self.hall.t = 0.0
        self.connect()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: setattr(self, "_stop", True))

        wall0 = time.monotonic()
        sim_start = utc_now()
        actions = sorted(self.scn.actions if self.scripted_actions else [], key=lambda a: a["at_s"])
        next_publish, seq = 0.0, {gw: 0 for gw in GATEWAYS}
        end = duration_s if duration_s is not None else self.scn.duration_s
        print(f"live: {self.scn.name}, speed x{self.speed}, "
              f"{'until Ctrl-C' if end <= 0 else f'{end:.0f} s simulated'}, broker {self.host}:{self.port}",
              flush=True)
        try:
            while not self._stop and (end <= 0 or self.hall.t <= end):
                t = self.hall.t
                delay = wall0 + t / self.speed - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                while not self.inbox.empty():
                    gw, delta = self.inbox.get()
                    self._handle_delta(gw, delta, t)
                while actions and actions[0]["at_s"] <= t:
                    a = actions.pop(0)
                    self.hall.apply_command(a["asset"], a["desired"])
                if t >= next_publish - 1e-9:
                    readings = self.sensors.measure(t)
                    self.truth_log.append({"t_s": round(t, 3), "values": _plain(self.hall.true_readings())})
                    ts = iso(sim_start + timedelta(seconds=t))
                    for gw in GATEWAYS:
                        seq[gw] += 1
                        msg = {"gw": gw, "ts": ts, "seq": seq[gw], "sent_at": iso(utc_now()),
                               "assets": readings[gw]}
                        self.clients[gw].publish(telemetry_topic(gw), json.dumps(msg), qos=1)
                        self.published += 1
                        self.messages_log.append({**msg, "t_s": round(t, 3)})
                    next_publish += cfg.publish_period_s
                apply_physical_faults(self.hall, self.scn.faults, t)
                self.hall.step(cfg.dt_s)
        finally:
            self.disconnect()
            self._write_outputs(sim_start)
        return self.out_dir

    def _write_outputs(self, sim_start: datetime) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        labels = {
            "scenario": self.scn.name,
            "mode": "live",
            "speed": self.speed,
            "sim_start": iso(sim_start),
            "sim_seconds": round(self.hall.t, 1),
            "published_messages": self.published,
            "faults": [dict(f.label(self.hall.t),
                            start_at=iso(sim_start + timedelta(seconds=f.start_s)))
                       for f in self.scn.faults],
        }
        (self.out_dir / "labels.json").write_text(json.dumps(labels, indent=2))
        for name, rows in (("commands", self.commands_log), ("truth", self.truth_log),
                           ("messages", self.messages_log)):
            with (self.out_dir / f"{name}.jsonl").open("w") as fh:
                for c in rows:
                    fh.write(json.dumps(c) + "\n")
        print(f"live: stopped after {self.hall.t:.0f} s simulated, {self.published} messages, "
              f"{len(self.commands_log)} commands -> {self.out_dir}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the data hall live over MQTT.")
    ap.add_argument("--scenario", type=Path, help="scenario YAML (default: normal operation)")
    ap.add_argument("--speed", type=float, default=1.0, help="simulated seconds per wall second")
    ap.add_argument("--duration", type=float, help="simulated seconds to run; 0 = until Ctrl-C")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--scripted-actions", action="store_true",
                    help="also apply the scenario's scripted actions (normally commands come over MQTT)")
    ap.add_argument("--out", type=Path, help="output folder for ground truth")
    ap.add_argument("--aws-certs", type=Path, metavar="DIR",
                    help="connect to AWS IoT Core with the certificate in DIR (tools/aws_devices.py writes it): "
                         "host from DIR/endpoint.txt, port 8883, client IDs dc-<gateway>")
    args = ap.parse_args()
    tls, prefix = None, ""
    if args.aws_certs:
        d = args.aws_certs
        tls = {"ca": str(d / "AmazonRootCA1.pem"), "cert": str(d / "device.pem.crt"), "key": str(d / "private.pem.key")}
        args.host, args.port, prefix = (d / "endpoint.txt").read_text().strip(), 8883, "dc-"

    if args.scenario:
        scn, _ = load_scenario(args.scenario)
    else:
        scn = ScenarioConfig(name="normal", duration_s=0)
    duration = args.duration if args.duration is not None else scn.duration_s
    sim = LiveSimulator(scn, host=args.host, port=args.port, speed=args.speed, out_dir=args.out,
                        scripted_actions=args.scripted_actions, tls=tls, client_prefix=prefix)
    sim.run(duration)


if __name__ == "__main__":
    main()
