"""Live fidelity check: E1 fault scenarios through the real local stack (LocalStack + MQTT).

The offline batch (experiments/batch.py) runs the same detector, state machine and Lambda code in
one process. This tool repeats a subset on the deployed stack, so the thesis can show that the
offline numbers carry over: MQTT, the bridge, EventBridge, Step Functions, the device shadow and
the gateway are all real here, at speed x10.

For each fault x mode x seed:
  1. switch the deployed Lambdas to the mode (DETECTOR d0/d2h, AUTOMATION notify/on)
  2. run the scenario live: fault after 5 simulated minutes, 30 minutes observed after it
  3. act as the human: approve high-risk plans (M2/M3), and in M1 carry out the playbook by hand
     through the device shadow, after the same sampled response time as offline (divided by the speed)
  4. score the run with experiments/metrics.py and append it to experiments/results/live_runs.csv

    python -m tools.live_experiment [--faults all] [--modes M1,M2,M3] [--seeds 1]     (make live-experiment)

About 4.5 minutes per run; the default (8 faults x 3 modes x 1 seed) takes about 1 h 50 min.
The deployed modes are restored to M3 (d2h, automation on) at the end.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

from common.awsenv import session, stack_outputs
from common.catalog import FAULT_CATALOG
from common.topology import GATEWAYS, gateway_of
from experiments.batch import FAULTS, MODES, human_delay
from experiments.metrics import run_metrics
from playbooks.catalog import PlanError, build_plan

from .approve import approval_item, decide
from .events import drain
from .incidents import plain, steps, summaries
from .prepare_run import drain_queue, prepare
from .procs import pipeline_running, start, stop, wait_for_line
from .reset_shadows import reset
from .warm import warm_up

ROOT = Path(__file__).resolve().parents[1]
SPEED, FAULT_AT, AFTER = 10.0, 300.0, 1800.0
OUT = ROOT / "experiments" / "results" / "live_runs.csv"
RUNS = ROOT / "runs" / "live-exp"
FIELDS = ["suite", "mode", "fault", "seed", "param", "human_delay_s", "detected", "mttd_s", "action_s",
          "incident_status", "exceeded", "recovered", "mttr_s", "exposure", "thermal_kmin", "alerts",
          "wrong_actions", "incidents", "observed_s", "runtime_s", "error"]


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def set_mode(sess, out: dict, mode: str) -> None:
    lam = sess.client("lambda")
    for fn, key, value in ((out["DetectorFunctionName"], "DETECTOR", MODES[mode]["detector"]),
                           (out["RemediationFunctionName"], "AUTOMATION", MODES[mode]["automation"])):
        env = lam.get_function_configuration(FunctionName=fn).get("Environment", {}).get("Variables", {})
        if env.get(key) == value:
            continue
        lam.update_function_configuration(FunctionName=fn, Environment={"Variables": {**env, key: value}})
        for _ in range(60):
            if lam.get_function_configuration(FunctionName=fn).get("LastUpdateStatus", "Successful") == "Successful":
                break
            time.sleep(1)
    warm_up(sess, out["DetectorFunctionName"], concurrency=10)


def alerts_queue(sess, out: dict) -> str:
    """A queue subscribed to the alerts topic, so alerts to humans can be counted."""
    sqs, sns = sess.client("sqs"), sess.client("sns")
    url = sqs.create_queue(QueueName="dc-selfheal-alert-capture")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    subs = sns.list_subscriptions_by_topic(TopicArn=out["AlertsTopicArn"]).get("Subscriptions", [])
    if not any(s["Endpoint"] == arn for s in subs):
        sns.subscribe(TopicArn=out["AlertsTopicArn"], Protocol="sqs", Endpoint=arn)
    return url


def scenario_file(fault: str, seed: int, folder: Path) -> Path:
    spec = yaml.safe_load((ROOT / "simulator" / "scenarios" / f"{fault}.yaml").read_text())
    spec.update(name=f"live-{fault}", seed=seed, duration_s=FAULT_AT + AFTER, actions=[])
    spec.pop("plot", None)
    for f in spec["faults"]:
        f["start_s"] = FAULT_AT
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "scenario.yaml"
    path.write_text(yaml.safe_dump(spec))
    return path


def latest_snapshot(telemetry) -> dict:
    snap = {}
    for gw in GATEWAYS:
        items = telemetry.query(KeyConditionExpression="gw = :g", ExpressionAttributeValues={":g": gw},
                                ScanIndexForward=False, Limit=1)["Items"]
        if items:
            snap[gw] = plain(items[0])
    return snap


def run_one(sess, out: dict, fault: str, mode: str, seed: int, alerts_url: str) -> dict:
    t_run = time.time()
    ddb, sqs = sess.resource("dynamodb"), sess.client("sqs")
    incidents, telemetry = ddb.Table(out["IncidentsTableName"]), ddb.Table(out["TelemetryTableName"])
    folder = RUNS / f"{fault}-{mode}-{seed}"
    delay = human_delay(seed)
    set_mode(sess, out, mode)
    prepare("local")
    drain(sqs, out["AnomalyQueueUrl"])
    drain_queue(sqs, alerts_url)
    started = iso(datetime.now(timezone.utc))
    bridge = start("live-exp-bridge", ["bridge", "--stage", "local"])
    live = None
    human_actions, handled, due = [], set(), []          # due: (wall time, kind, data)
    try:
        wait_for_line("live-exp-bridge", "connected to MQTT", bridge)
        reset()
        live = start("live-exp-sim", ["simulator.live", "--scenario", str(scenario_file(fault, seed, folder)),
                                      "--speed", str(SPEED), "--duration", str(FAULT_AT + AFTER), "--out", str(folder)])
        wait_for_line("live-exp-sim", "live:", live)
        sim_wall0 = time.time()
        while live.poll() is None:
            for inc in summaries(incidents, since=started):
                key = inc["id"]
                if key in handled:
                    continue
                if inc.get("status") == "awaiting_approval":
                    handled.add(key)
                    due.append((time.time() + delay / SPEED, "approve", key))
                elif (mode == "M1" and inc.get("status") == "notified"
                      and FAULT_CATALOG.get(inc.get("fault_type"), ("", "notify_only"))[1] != "notify_only"):
                    handled.add(key)
                    ev = {"fault_type": inc["fault_type"], "target": inc["target"], "asset": inc["asset"],
                          "playbook": inc["playbook"], "evidence": {}}
                    due.append((time.time() + delay / SPEED, "human", (ev, None, 0)))
            for item in [d for d in due if d[0] <= time.time()]:
                due.remove(item)
                _, kind, data = item
                if kind == "approve":
                    appr = approval_item(incidents, data)
                    if appr:
                        decide(sess, out, data, appr["nonce"], "approve", "simulated operator")
                else:
                    ev, plan, k = data
                    t_s = (time.time() - sim_wall0) * SPEED
                    if plan is None:
                        try:
                            plan = build_plan(ev, latest_snapshot(telemetry))
                        except PlanError as exc:
                            human_actions.append({"t_s": t_s, "event": f"{ev['fault_type']}:{ev['target']}",
                                                  "action": "none", "reason": str(exc)})
                            continue
                    stg = plan["stages"][k]
                    by_gw: dict = {}
                    for asset, desired in stg["commands"].items():
                        by_gw.setdefault(gateway_of(asset), {})[asset] = desired
                    for gw, desired in by_gw.items():
                        sqs.send_message(QueueUrl=out["ShadowQueueUrl"], MessageBody=json.dumps(
                            {"thing": gw, "payload": {"state": {"desired": {**desired, "cmd_id": f"human:{k}:{gw}"}}}}))
                    human_actions.append({"t_s": t_s, "event": f"{ev['fault_type']}:{ev['target']}",
                                          "action": stg["name"]})
                    if k + 1 < len(plan["stages"]):
                        due.append((time.time() + 120.0 / SPEED, "human", (ev, plan, k + 1)))
            time.sleep(1.0)
        time.sleep(3)
    finally:
        stop(live, bridge)

    labels = json.loads((folder / "labels.json").read_text())
    sim_start = parse(labels["sim_start"])

    def to_sim(at: str) -> str:              # Lambda clocks are wall time; the metrics use sim time
        return iso(sim_start + (parse(at) - sim_start) * SPEED)

    events = drain(sqs, out["AnomalyQueueUrl"], wait=1)
    for e in events:
        e["t_s"] = (int(e["seq"]) - 1) * 10.0
    run_incidents = []
    for inc in summaries(incidents, since=started):
        inc["log"] = [{**s, "at": to_sim(s["at"])} for s in steps(incidents, inc["id"])]
        run_incidents.append(inc)
    read = lambda name: [json.loads(x) for x in (folder / f"{name}.jsonl").read_text().splitlines() if x]  # noqa: E731
    truth = [{**t, "wall_start": labels["sim_start"]} for t in read("truth")]
    res = SimpleNamespace(
        labels=[{"type": f["type"], "target": f["target"], "start_s": f["start_s"], "normal_event": False}
                for f in labels["faults"]],
        events=events, incidents=run_incidents, human_actions=human_actions, truth=truth,
        messages=read("messages"), commands=[{"t_s": c["sim_t"]} for c in read("commands")],
        alerts=drain_queue(sqs, alerts_url) * [None], dropped=0)
    row = {"suite": "live", "mode": mode, "fault": fault, "seed": seed, "param": SPEED, "human_delay_s": delay,
           **run_metrics(res)}
    row["runtime_s"] = round(time.time() - t_run, 1)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--faults", default="all")
    ap.add_argument("--modes", default="M1,M2,M3")
    ap.add_argument("--seeds", type=int, default=1, help="seeds 1001.. (the same as the offline batch)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--after", type=float, default=AFTER, help="simulated seconds observed after the fault")
    args = ap.parse_args()
    globals()["AFTER"] = args.after
    if pipeline_running():
        sys.exit("The pipeline is running (make pipeline-up). Stop it first: make pipeline-down")
    sess = session("local")
    out = stack_outputs(sess, "local")
    if "ApprovalFunctionName" not in out:
        sys.exit("Deploy Step 6 first: make deploy-local")
    faults = FAULTS if args.faults == "all" else args.faults.split(",")
    todo = [(f, m, s) for s in range(1001, 1001 + args.seeds) for f in faults for m in args.modes.split(",")]
    done = set()
    if args.out.exists():
        with open(args.out) as fh:
            done = {(r["fault"], r["mode"], int(r["seed"])) for r in csv.DictReader(fh) if not r.get("error")}
    todo = [t for t in todo if t not in done]
    print(f"{len(todo)} live runs to do (about {len(todo) * 4.5 / 60:.1f} h); results -> {args.out}", flush=True)
    alerts_url = alerts_queue(sess, out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    new = not args.out.exists()
    try:
        with open(args.out, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            for n, (fault, mode, seed) in enumerate(todo, 1):
                try:
                    row = run_one(sess, out, fault, mode, seed, alerts_url)
                except Exception as exc:  # noqa: BLE001 - keep going with the next run
                    row = {"suite": "live", "mode": mode, "fault": fault, "seed": seed, "error": repr(exc)[:300]}
                w.writerow(row)
                fh.flush()
                print(f"  {n}/{len(todo)} {fault} {mode} seed {seed}: "
                      f"{row.get('error') or row.get('incident_status')}  detect {row.get('mttd_s')} s  "
                      f"recover {row.get('mttr_s')} s", flush=True)
    finally:
        set_mode(sess, out, "M3")
        print("deployed stack restored to M3 (d2h, automation on)")


if __name__ == "__main__":
    main()
