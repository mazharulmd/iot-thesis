"""End-to-end check of the local stack (Steps 3 to 5).

Starts the bridge and a live simulator in which CRAH unit 2 fails after 5 simulated
minutes (speed x10), then verifies:
  Step 3  commands via device shadows (including one sent while offline),
          telemetry stored for all gateways, the Lambda invoked for all gateways
  Step 4  the detector publishes crah_fan_failure/crah2 to the anomaly bus,
          and no automated-playbook anomaly is raised before the fault
  Step 5  the cooling_unit_failover playbook mitigates the failure with no human input:
          incident mitigated, standby crah5 running in zone 2, zone 2 inlets back below 27 °C,
          and no incident escalated
Also reports (informational, not pass/fail) the Lambda cold start and the latency from
gateway send to detector finish over a window after detection, split into time inside
the handler and time outside it. Latency is measured properly by `make latency`.
Stops everything afterwards.

    python -m tools.e2e_check                 (make e2e)        LocalStack + Mosquitto + bridge
    python -m tools.e2e_check --stage dev     (make aws-check)  real AWS: gateways on IoT Core

On AWS there is no bridge: the gateways connect to IoT Core with the certificate in certs/
(make aws-devices), the topic rule stores telemetry and invokes the detector, and commands go
through IoT Core device shadows. The same checks apply.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from common.awsenv import session, stack_outputs
from common.topology import GATEWAYS

from .events import drain
from .incidents import steps, summaries
from .prepare_run import prepare
from .latency import describe, snapshot, window
from .procs import pipeline_running, start, stop, wait_for_line
from .shadow_api import Shadows
from .status import gather
from .warm import warm_up

LIVE_OUT = Path("runs/e2e-live")
CERTS = Path(__file__).resolve().parents[1] / "certs"
SPEED = 10
LATENCY_WINDOW_S = 20
MITIGATION_TIMEOUT_S = 240
INLET_LIMIT_C = 27.0
WARM_CONTAINERS = 10       # LocalStack's async poller hands up to 10 events at once to the function


def lambda_alive(row: dict, max_age_s: float = 120) -> bool:
    """The detector has run for this gateway recently (0.0 s ago counts: it is not 'never')."""
    return row["lambda_msgs"] > 0 and row["seen_s_ago"] is not None and row["seen_s_ago"] < max_age_s


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def gateway_args(stage: str) -> list[str]:
    """Extra live-simulator arguments: on AWS the gateways connect to IoT Core with the certificate."""
    if stage == "local":
        return []
    if not (CERTS / "endpoint.txt").exists():
        sys.exit("No device certificate: run make aws-devices first")
    return ["--aws-certs", str(CERTS)]


def sensor_to_command_ms(telemetry, event: dict, incident_id: str, live_out: Path) -> float | None:
    """Sensor timestamp of the message that triggered detection -> command received at the gateway."""
    item = telemetry.get_item(Key={"gw": event["gw"], "ts": event["ts"]}).get("Item")
    log = live_out / "commands.jsonl"
    if not item or not log.exists():
        return None
    cmds = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    first = next((c for c in cmds if str(c.get("cmd_id") or "").startswith(incident_id)), None)
    if not first:
        return None
    return (parse(first["received_at"]) - parse(item["sent_at"])).total_seconds() * 1000.0


def main() -> None:
    ap = argparse.ArgumentParser(description="End-to-end check")
    ap.add_argument("--stage", default="local")
    stage = ap.parse_args().stage
    local = stage == "local"
    if pipeline_running():
        sys.exit("The pipeline is already running (make pipeline-up). Stop it first: make pipeline-down")

    sess = session(stage)
    try:
        out = stack_outputs(sess, stage)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Stacks not found ({exc}). Run: " + ("make up && make deploy-local" if local else "make aws-deploy"))
    if "StateMachineArn" not in out:
        sys.exit("Remediation stack not found. Run: " + ("make deploy-local" if local else "make aws-deploy"))
    extra = gateway_args(stage)
    shadows = Shadows(stage, sess)
    ddb = sess.resource("dynamodb")
    telemetry = ddb.Table(out["TelemetryTableName"])
    incidents = ddb.Table(out["IncidentsTableName"])
    sqs = sess.client("sqs")
    drain(sqs, out["AnomalyQueueUrl"])                         # forget events from earlier runs
    prepare(stage)                          # future-stamped telemetry, locks and queued commands of earlier runs

    print("Warming up the detector Lambda ...", flush=True)
    cold_s = warm_up(sess, out["DetectorFunctionName"], concurrency=WARM_CONTAINERS)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    results: list[tuple[str, bool | None, str]] = [
        ("detector Lambda warm-up", None, f"{WARM_CONTAINERS} containers in {cold_s:.1f} s")]
    bridge = start("e2e-bridge", ["bridge", "--stage", "local"]) if local else None
    live = None
    events: list[dict] = []
    try:
        if bridge:
            wait_for_line("e2e-bridge", "connected to MQTT", bridge)
        shadows.reset()
        if local:                                           # waits over MQTT in its own process
            pending = start("e2e-pending-cmd", ["tools.send_command", "crah3", '{"fan_pct": 65}'])
        else:
            pending = shadows.send("crah3", {"fan_pct": 65}, wait=False)
        time.sleep(1)
        live = start("e2e-live", ["simulator.live", "--scenario", "simulator/scenarios/e2e_crah_failure.yaml",
                                  "--speed", str(SPEED), "--duration", "0", "--out", str(LIVE_OUT), *extra])
        wait_for_line("e2e-live", "live:", live)
        ok = pending.wait(timeout=30) == 0 if local else shadows.wait(pending, timeout=30)["ok"]
        results.append(("command sent while offline applied on connect", ok, "crah3 fan_pct=65 via shadow get"))
        shadows.send("crah3", {"fan_mode": "auto", "fan_pct": None})

        res = shadows.send("crah1", {"fan_pct": 70})
        results.append(("command crah1 fan_pct=70 applied via shadow", res["ok"],
                        f"round trip {res.get('round_trip_ms', '-')} ms"))
        shadows.send("crah1", {"fan_mode": "auto", "fan_pct": None})

        print("Pipeline running; CRAH 2 fails 5 simulated minutes in (30 s at x10). Waiting for detection "
              "...", flush=True)
        deadline = time.time() + 180
        while time.time() < deadline:
            events += drain(sqs, out["AnomalyQueueUrl"], wait=2)
            if any(e["fault_type"] == "crah_fan_failure" and e["target"] == "crah2" for e in events):
                break
        print("Waiting for the cooling failover playbook to act and verify ...", flush=True)
        incident = None
        deadline = time.time() + MITIGATION_TIMEOUT_S
        while time.time() < deadline:
            incident = next((i for i in summaries(incidents, since=started)
                             if i.get("fault_type") == "crah_fan_failure" and i.get("target") == "crah2"), None)
            if incident and incident.get("status") in ("mitigated", "escalated"):
                break
            time.sleep(3)
        events += drain(sqs, out["AnomalyQueueUrl"], wait=1)
        latest = {gw: telemetry.query(KeyConditionExpression="gw = :g", ExpressionAttributeValues={":g": gw},
                                      ScanIndexForward=False, Limit=1)["Items"][0] for gw in ("zone2", "plant")}
        a = snapshot(stage)
        print(f"Measuring latency for {LATENCY_WINDOW_S} s ...", flush=True)
        time.sleep(LATENCY_WINDOW_S)
        b = snapshot(stage)
        rows = gather(stage)
    finally:
        stop(live, bridge)

    for gw in GATEWAYS:
        n = telemetry.query(KeyConditionExpression="gw = :g AND ts >= :t",
                            ExpressionAttributeValues={":g": gw, ":t": started}, Select="COUNT")["Count"]
        results.append((f"telemetry stored for {gw}", n > 0, f"{n} messages since start"))
    for r in rows:
        ok = lambda_alive(r)
        results.append((f"detector Lambda invoked for {r['gw']}", ok, f"{r['lambda_msgs']} messages"))
    results.append(("latency send -> detector done (x10 load)", None, describe(window(a, b))))

    labels = json.loads((LIVE_OUT / "labels.json").read_text())
    fault_at = parse(labels["faults"][0]["start_at"])
    hit = next((e for e in events if e["fault_type"] == "crah_fan_failure" and e["target"] == "crah2"), None)
    delay = f"{(parse(hit['ts']) - fault_at).total_seconds():.0f} s simulated after the fault" if hit else "not seen"
    results.append(("anomaly event crah_fan_failure/crah2 published", hit is not None, delay))
    early = [e for e in events if parse(e["ts"]) < fault_at and e["playbook"] != "notify_only"]
    results.append(("no automated anomaly before the fault", not early,
                    ", ".join(f"{e['fault_type']}:{e['target']}" for e in early) or "none"))

    # ---------------------------------------------------------------- Step 5: remediation
    status = incident.get("status") if incident else None
    if incident and incident.get("verified_ts"):
        info = f"verified {(parse(incident['verified_ts']) - fault_at).total_seconds():.0f} s simulated after the fault"
    else:
        info = f"status {status or 'no incident'}" + (f": {incident.get('reason')}" if incident and incident.get("reason") else "")
    results.append(("playbook mitigated crah2 failure, no human input", status == "mitigated", info))
    if incident and hit:
        ms = sensor_to_command_ms(telemetry, hit, incident["id"], LIVE_OUT)
        results.append(("sensor message -> first command at the gateway", None,
                        f"{ms:.0f} ms (detect, decide, act through the shadow)" if ms is not None else "not measured"))
    sb = latest["plant"]["assets"]["crah5"]
    results.append(("standby crah5 running in zone 2", sb["status"] == "on" and int(sb["zone"]) == 2,
                    f"status {sb['status']}, zone {sb['zone']}, fan {float(sb['fan_pct']):.0f} %"))
    inlets = {a: float(v["t_in"]) for a, v in latest["zone2"]["assets"].items() if a.startswith("rack")}
    results.append(("zone 2 rack inlets back below 27 °C", max(inlets.values()) <= INLET_LIMIT_C,
                    f"max {max(inlets.values()):.1f} °C"))
    run_incidents = summaries(incidents, since=started)
    escalated = [i for i in run_incidents if i.get("status") == "escalated"]
    results.append(("no incident escalated", not escalated,
                    ", ".join(f"{i['fault_type']}:{i['target']} ({i.get('reason', '')[:60]})" for i in escalated) or "none"))

    print()
    for name, ok, info in results:
        print(f"  [{'INFO' if ok is None else 'PASS' if ok else 'FAIL'}] {name:48s} {info}")
    if events:
        print("\n  anomaly events seen:")
        for e in sorted(events, key=lambda e: e["ts"]):
            print(f"    {e['ts']}  {e['fault_type']}:{e['target']}  ({e['playbook']})")
    if incident:
        print(f"\n  incident {incident['id']} ({incident.get('correlated', 0)} related events joined it):")
        for st in steps(incidents, incident["id"]):
            what = st.get("name") or st.get("reason") or st.get("ticket") or st.get("fault_type", "")
            print(f"    {st['at'][11:19]}  {st['step']:16s} {str(what)[:90]}")
    others = [i for i in run_incidents if not incident or i["id"] != incident["id"]]
    if others:
        print("\n  other incidents:")
        for i in others:
            print(f"    {i['fault_type']}:{i['target']}  {i.get('status')}")
    passed = all(ok is not False for _, ok, _ in results)
    print("\nEND-TO-END CHECK PASSED" if passed else "\nEND-TO-END CHECK FAILED (see logs/e2e-*.log)")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
