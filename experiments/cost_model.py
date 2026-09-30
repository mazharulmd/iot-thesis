"""E3: monthly AWS cost of the framework, projected from measured usage per message.

    python -m experiments.cost_model [--prices experiments/prices.yaml]      (make aws-cost)

Usage per telemetry message comes from the load test (experiments/results/e2_usage.json, written
by `make aws-loadtest`); until that exists, conservative defaults are used and marked as such.
Facility sizes: small = 1 data hall (5 gateways, 20 racks, the testbed), medium = 10 halls,
large = 100 halls; every gateway sends one message per 10 s. Remediation activity per hall and
month is an assumption (below), because it depends on how often equipment fails.

Output: experiments/results/e3_cost.md (and .csv), with list prices, the always-free allowances
applied, and DynamoDB both on demand and with provisioned capacity sized to the load.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SECONDS_PER_MONTH = 30 * 24 * 3600
PERIOD_S = 10
GATEWAYS_PER_HALL = 5
RACKS_PER_HALL = 20
SIZES = {"small (1 hall)": 1, "medium (10 halls)": 10, "large (100 halls)": 100}

DEFAULT_USAGE = {
    "source": "defaults (not yet measured on AWS)",
    "detector_ms": 60.0,            # average billed duration per telemetry message
    "detector_mb": 512,
    "telemetry_wru": 2.0,           # one ~1.5 KB item
    "stats_wru": 1.0,               # IngestStats update
    "history_rru": 2.0,             # 9-item query, eventually consistent
    "log_bytes_per_invocation": 350,
    "item_kb": 1.5,
    "retention_days": 30,
}
# Remediation activity per data hall per month (assumption; see docs/experiments.md)
ACTIVITY = {
    "automated_incidents": 5, "notify_incidents": 30, "correlated_events_per_incident": 3,
    "transitions_per_automated": 30, "transitions_per_notify": 5, "transitions_per_correlated": 4,
    "remediation_invocations_per_automated": 12, "remediation_ms": 150, "remediation_mb": 256,
    "shadow_operations_per_automated": 12, "emails_per_automated": 2, "emails_per_notify": 1,
}


def load_prices(path: Path = HERE / "prices.yaml") -> dict:
    return yaml.safe_load(path.read_text())


def load_usage(path: Path = RESULTS / "e2_usage.json") -> dict:
    usage = dict(DEFAULT_USAGE)
    if path.exists():
        usage.update(json.loads(path.read_text()))
    return usage


def telemetry_cost(messages: float, p: dict, u: dict) -> dict:
    """List-price cost of `messages` telemetry messages through IoT Core, the rule and the detector."""
    gb_s = messages * u["detector_ms"] / 1000 * u["detector_mb"] / 1024
    return {
        "iot_core": messages * (p["iot_core"]["messages_per_million"] + p["iot_core"]["rules_triggered_per_million"]
                                + 2 * p["iot_core"]["actions_applied_per_million"]) / 1e6,
        "lambda": gb_s * p["lambda"]["gb_second"] + messages * p["lambda"]["requests_per_million"] / 1e6,
        "dynamodb": messages * ((u["telemetry_wru"] + u["stats_wru"]) * p["dynamodb"]["on_demand_write_units_per_million"]
                                + u["history_rru"] * p["dynamodb"]["on_demand_read_units_per_million"]) / 1e6,
        "cloudwatch_logs": messages * u["log_bytes_per_invocation"] / 1e9 * p["cloudwatch_logs"]["ingest_per_gb"],
        "gb_seconds": gb_s,
    }


def monthly(halls: int, p: dict, u: dict, a: dict = ACTIVITY) -> dict:
    gws = halls * GATEWAYS_PER_HALL
    msgs = gws * SECONDS_PER_MONTH / PERIOD_S
    t = telemetry_cost(msgs, p, u)
    inc_auto, inc_notify = halls * a["automated_incidents"], halls * a["notify_incidents"]
    correlated = inc_auto * a["correlated_events_per_incident"]
    transitions = (inc_auto * a["transitions_per_automated"] + inc_notify * a["transitions_per_notify"]
                   + correlated * a["transitions_per_correlated"])
    rem_invocations = inc_auto * a["remediation_invocations_per_automated"] + (inc_notify + correlated) * 2
    rem_gb_s = rem_invocations * a["remediation_ms"] / 1000 * a["remediation_mb"] / 1024
    events = inc_auto + inc_notify + correlated
    emails = inc_auto * a["emails_per_automated"] + inc_notify * a["emails_per_notify"]
    storage_gb = gws * (86400 / PERIOD_S) * u["retention_days"] * u["item_kb"] / 1e6
    log_gb = (msgs + rem_invocations) * u["log_bytes_per_invocation"] / 1e9
    wcu = math.ceil(gws / PERIOD_S * (u["telemetry_wru"] + u["stats_wru"]) * 1.5)   # 50 % headroom
    rcu = math.ceil(gws / PERIOD_S * u["history_rru"] * 1.5)

    items = {
        "IoT Core (messages, rule, 2 actions, shadows)": t["iot_core"]
        + (inc_auto * a["shadow_operations_per_automated"]) * p["iot_core"]["shadow_operations_per_million"] / 1e6
        + gws * SECONDS_PER_MONTH / 60 * p["iot_core"]["connection_minutes_per_million"] / 1e6,
        "Lambda (detector + remediation)": t["lambda"] + rem_gb_s * p["lambda"]["gb_second"]
        + rem_invocations * p["lambda"]["requests_per_million"] / 1e6,
        "DynamoDB on demand (requests + storage)": t["dynamodb"] + storage_gb * p["dynamodb"]["storage_gb_month"],
        "Step Functions (Standard)": transitions * p["step_functions"]["standard_transitions_per_thousand"] / 1000,
        "EventBridge + SNS": events * p["eventbridge"]["custom_events_per_million"] / 1e6
        + emails * p["sns"]["email_per_100k"] / 1e5,
        "CloudWatch Logs": log_gb * (p["cloudwatch_logs"]["ingest_per_gb"] + p["cloudwatch_logs"]["storage_gb_month"]),
    }
    list_total = sum(items.values())
    f = p["always_free"]
    free = (min(t["gb_seconds"] + rem_gb_s, f["lambda_gb_seconds"]) * p["lambda"]["gb_second"]
            + min(msgs + rem_invocations, f["lambda_requests"]) * p["lambda"]["requests_per_million"] / 1e6
            + min(transitions, f["step_functions_transitions"]) * p["step_functions"]["standard_transitions_per_thousand"] / 1000
            + min(emails, f["sns_emails"]) * p["sns"]["email_per_100k"] / 1e5
            + min(log_gb, f["cloudwatch_logs_gb"]) * p["cloudwatch_logs"]["ingest_per_gb"]
            + min(storage_gb, f["dynamodb_storage_gb"]) * p["dynamodb"]["storage_gb_month"])
    provisioned = (wcu * p["dynamodb"]["provisioned_wcu_hour"] + rcu * p["dynamodb"]["provisioned_rcu_hour"]) * 730
    provisioned_after_free = (max(0, wcu - f["dynamodb_provisioned_wcu"]) * p["dynamodb"]["provisioned_wcu_hour"]
                              + max(0, rcu - f["dynamodb_provisioned_rcu"]) * p["dynamodb"]["provisioned_rcu_hour"]) * 730
    return {"halls": halls, "gateways": gws, "racks": halls * RACKS_PER_HALL, "messages": msgs, "items": items,
            "list_total": list_total, "after_free": max(0.0, list_total - free),
            "ddb_on_demand_requests": t["dynamodb"], "ddb_provisioned": provisioned,
            "ddb_provisioned_after_free": provisioned_after_free, "wcu": wcu, "rcu": rcu, "storage_gb": storage_gb}


def estimate_load_test(levels: list[int], minutes: float, p: dict, u: dict | None = None) -> float:
    """List-price cost of a load test (no free tier): telemetry path only."""
    u = u or load_usage()
    msgs = sum(levels) * minutes * 60 / PERIOD_S
    return sum(v for k, v in telemetry_cost(msgs, p, u).items() if k != "gb_seconds")


def report(p: dict, u: dict) -> str:
    rows = {name: monthly(h, p, u) for name, h in SIZES.items()}
    names = list(rows)
    lines = [f"Monthly cost in USD ({p.get('as_of')}; usage: {u.get('source')}).", "",
             "| Service | " + " | ".join(names) + " |", "| --- |" + " --- |" * len(names)]
    for item in next(iter(rows.values()))["items"]:
        lines.append(f"| {item} | " + " | ".join(f"{rows[n]['items'][item]:,.2f}" for n in names) + " |")
    lines += [
        "| **Total at list price** | " + " | ".join(f"**{rows[n]['list_total']:,.2f}**" for n in names) + " |",
        "| Total after always-free allowances | " + " | ".join(f"{rows[n]['after_free']:,.2f}" for n in names) + " |",
        "| Per rack per month (list price) | " + " | ".join(f"{rows[n]['list_total'] / rows[n]['racks']:,.3f}" for n in names) + " |",
        "", "DynamoDB requests on demand vs provisioned capacity sized to the load (50 % headroom):", "",
        "| | " + " | ".join(names) + " |", "| --- |" + " --- |" * len(names),
        "| Telemetry messages per month | " + " | ".join(f"{rows[n]['messages']:,.0f}" for n in names) + " |",
        "| On demand (requests) | " + " | ".join(f"{rows[n]['ddb_on_demand_requests']:,.2f}" for n in names) + " |",
        "| Provisioned (WCU / RCU) | " + " | ".join(f"{rows[n]['ddb_provisioned']:,.2f} ({rows[n]['wcu']} / {rows[n]['rcu']})"
                                                  for n in names) + " |",
        "| Provisioned after the 25/25 always-free units | " + " | ".join(
            f"{rows[n]['ddb_provisioned_after_free']:,.2f}" for n in names) + " |",
        "", "Assumed remediation activity per hall and month: " + ", ".join(f"{k.replace('_', ' ')} {v}"
                                                                            for k, v in ACTIVITY.items()) + ".",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prices", type=Path, default=HERE / "prices.yaml")
    ap.add_argument("--usage", type=Path, default=RESULTS / "e2_usage.json")
    args = ap.parse_args()
    p, u = load_prices(args.prices), load_usage(args.usage)
    text = report(p, u)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "e3_cost.md").write_text(text + "\n")
    with open(RESULTS / "e3_cost.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["size", "halls", "gateways", "messages", "list_total", "after_free", "ddb_on_demand_requests",
                    "ddb_provisioned", "ddb_provisioned_after_free"])
        for name, h in SIZES.items():
            m = monthly(h, p, u)
            w.writerow([name, h, m["gateways"], round(m["messages"]), round(m["list_total"], 2), round(m["after_free"], 2),
                        round(m["ddb_on_demand_requests"], 2), round(m["ddb_provisioned"], 2),
                        round(m["ddb_provisioned_after_free"], 2)])
    print(text)


if __name__ == "__main__":
    main()
