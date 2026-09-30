"""Live check of the approval guardrail (Step 6) on the local stack.

UPS 1's battery starts overheating 5 simulated minutes in (speed x10). The ups_load_transfer
playbook is high risk, so the execution must wait for a human. The check then:
  * confirms nothing was sent while waiting (UPS 1 still carries load),
  * opens the approval link (GET shows the plan and buttons, decides nothing),
  * approves with a POST to the function URL, exactly as the email link's button does,
  * confirms the link cannot be used twice,
  * waits until the plan was rechecked on fresh telemetry, acted and verified (UPS 1 load ~0).

    python -m tools.e2e_approval                (make e2e-approval)   local stack
    python -m tools.e2e_approval --stage dev    (part of make aws-check)  real AWS: IoT Core, public URL
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request

from common.awsenv import session, stack_outputs

from .approve import approval_item, decide, link
from .incidents import steps, summaries
from .prepare_run import prepare
from .e2e_check import gateway_args
from .procs import pipeline_running, start, stop, wait_for_line
from .shadow_api import Shadows
from .warm import warm_up

SPEED = 10
TIMEOUT_S = 240


def wait_incident(incidents, since: str, statuses: set[str], timeout: float) -> dict | None:
    deadline = time.time() + timeout
    inc = None
    while time.time() < deadline:
        inc = next((i for i in summaries(incidents, since=since)
                    if i.get("fault_type") == "ups_battery_overheat" and i.get("target") == "ups1"), None)
        if inc and inc.get("status") in statuses:
            return inc
        time.sleep(2)
    return inc


def latest(telemetry, gw: str) -> dict:
    return telemetry.query(KeyConditionExpression="gw = :g", ExpressionAttributeValues={":g": gw},
                           ScanIndexForward=False, Limit=1)["Items"][0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Live check of the approval guardrail")
    ap.add_argument("--stage", default="local")
    stage = ap.parse_args().stage
    local = stage == "local"
    if pipeline_running():
        sys.exit("The pipeline is already running (make pipeline-up). Stop it first: make pipeline-down")
    sess = session(stage)
    out = stack_outputs(sess, stage)
    if "ApprovalUrl" not in out:
        sys.exit("Approval function not found. Run: " + ("make deploy-local" if local else "make aws-deploy"))
    extra = gateway_args(stage)
    shadows = Shadows(stage, sess)
    ddb = sess.resource("dynamodb")
    incidents, telemetry = ddb.Table(out["IncidentsTableName"]), ddb.Table(out["TelemetryTableName"])
    prepare(stage)
    warm_up(sess, out["DetectorFunctionName"], concurrency=10)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results: list[tuple[str, bool | None, str]] = []
    bridge = start("e2e-approval-bridge", ["bridge", "--stage", "local"]) if local else None
    live = None
    inc = None
    plant = None
    try:
        if bridge:
            wait_for_line("e2e-approval-bridge", "connected to MQTT", bridge)
        shadows.reset()
        live = start("e2e-approval-live", ["simulator.live", "--scenario", "simulator/scenarios/e2e_ups_overheat.yaml",
                                           "--speed", str(SPEED), "--duration", "0", "--out", "runs/e2e-approval-live",
                                           *extra])
        wait_for_line("e2e-approval-live", "live:", live)
        print("Pipeline running; UPS 1 starts overheating 5 simulated minutes in. Waiting for the approval request ...",
              flush=True)
        inc = wait_incident(incidents, started, {"awaiting_approval", "escalated", "mitigated"}, TIMEOUT_S)
        results.append(("high-risk plan waits for approval", bool(inc) and inc.get("status") == "awaiting_approval",
                        f"status {inc.get('status') if inc else 'no incident'}"))
        if not inc or inc.get("status") != "awaiting_approval":
            raise LookupError("no approval request")
        time.sleep(6)                                        # 60 simulated seconds of waiting
        ups1 = float(latest(telemetry, "plant")["assets"]["ups1"]["load_kw"])
        results.append(("nothing sent while waiting", ups1 > 50, f"ups1 still carries {ups1:.0f} kW"))

        item = approval_item(incidents, inc["id"])
        url = link(out, inc["id"], item["nonce"])
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                body = resp.read().decode()
            ok = resp.status == 200 and "Approve" in body and "Reject" in body
            results.append(("approval link opens the plan (GET decides nothing)", ok, f"HTTP {resp.status}"))
            res = decide(sess, out, inc["id"], item["nonce"], "approve", "e2e check", via_url=True)
            results.append(("approved with a POST to the function URL", res["status"] == 200, f"HTTP {res['status']}"))
            again = decide(sess, out, inc["id"], item["nonce"], "approve", "e2e check", via_url=True)
            results.append(("link cannot be used twice", again["status"] == 409, f"HTTP {again['status']}"))
        except (urllib.error.URLError, OSError) as exc:
            results.append(("approval function URL reachable", False, f"{exc}; approving by direct invoke instead"))
            res = decide(sess, out, inc["id"], item["nonce"], "approve", "e2e check")
            results.append(("approved by direct invoke", res.get("status") == 200, str(res)))

        print("Approved; waiting for the recheck, the transfer and its verification ...", flush=True)
        inc = wait_incident(incidents, started, {"mitigated", "escalated", "rejected"}, TIMEOUT_S)
        plant = latest(telemetry, "plant")["assets"]
    except LookupError:
        pass                                                 # reported below
    finally:
        stop(live, bridge)

    if plant is not None:
        trail = [s["step"] for s in steps(incidents, inc["id"])]
        results.append(("plan rechecked on fresh telemetry after approval", "rechecked_after_approval" in trail, ""))
        results.append(("load transferred and verified", inc.get("status") == "mitigated",
                        f"status {inc.get('status')}" + (f": {inc.get('reason')}" if inc.get("reason") else "")))
        results.append(("ups1 load now near zero", float(plant["ups1"]["load_kw"]) <= 5,
                        f"ups1 {float(plant['ups1']['load_kw']):.0f} kW, ups2 {float(plant['ups2']['load_kw']):.0f} kW"))

    print()
    for name, ok, info in results:
        print(f"  [{'INFO' if ok is None else 'PASS' if ok else 'FAIL'}] {name:52s} {info}")
    if inc:
        print(f"\n  incident {inc['id']}:")
        for st in steps(incidents, inc["id"]):
            what = st.get("name") or st.get("reason") or st.get("by") or st.get("ticket") or ""
            print(f"    {st['at'][11:19]}  {st['step']:26s} {str(what)[:80]}")
    passed = all(ok is not False for _, ok, _ in results)
    print("\nAPPROVAL CHECK PASSED" if passed else "\nAPPROVAL CHECK FAILED (see logs/e2e-approval-*.log)")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
