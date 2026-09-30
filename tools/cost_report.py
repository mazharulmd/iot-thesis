"""E3, measured: what the AWS test runs actually cost, from Cost Explorer.

    python -m tools.cost_report --start 2026-10-01 [--end 2026-10-04]        (make aws-bill)

Reports usage charges (before credits) per service for resources tagged Project=dc-selfheal, and
the account's total usage charges over the same days (untagged items such as the CDK bootstrap
bucket show up only there). Writes experiments/results/e3_measured.md.

Two one-time settings in the Billing console are needed first, and data appears with about a day
of delay: open Cost Explorer once (it takes up to 24 h to start), and activate the user-defined
cost allocation tag "Project". Each Cost Explorer API request costs USD 0.01.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from common.awsenv import session

RESULTS = Path(__file__).resolve().parents[1] / "experiments" / "results"


def costs(ce, start: str, end: str, tag: bool) -> dict[str, float]:
    usage_only = {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}}
    flt = {"And": [usage_only, {"Tags": {"Key": "Project", "Values": ["dc-selfheal"]}}]} if tag else usage_only
    out: dict[str, float] = {}
    kw = {"TimePeriod": {"Start": start, "End": end}, "Granularity": "MONTHLY", "Metrics": ["UnblendedCost"],
          "Filter": flt, "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}]}
    while True:
        resp = ce.get_cost_and_usage(**kw)
        for period in resp["ResultsByTime"]:
            for g in period["Groups"]:
                out[g["Keys"][0]] = out.get(g["Keys"][0], 0.0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        if not resp.get("NextPageToken"):
            return out
        kw["NextPageToken"] = resp["NextPageToken"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="dev")
    ap.add_argument("--start", required=True, help="first day, YYYY-MM-DD")
    ap.add_argument("--end", default=str(date.today() + timedelta(days=1)), help="day after the last, YYYY-MM-DD")
    args = ap.parse_args()
    ce = session(args.stage).client("ce", region_name="us-east-1")
    tagged, total = costs(ce, args.start, args.end, True), costs(ce, args.start, args.end, False)
    services = sorted(set(tagged) | set(total), key=lambda s: -total.get(s, 0))
    lines = [f"Usage charges before credits, {args.start} to {args.end} (exclusive), USD.", "",
             "| Service | Tagged Project=dc-selfheal | Whole account |", "| --- | --- | --- |"]
    for s in services:
        if tagged.get(s, 0) >= 0.005 or total.get(s, 0) >= 0.005:
            lines.append(f"| {s} | {tagged.get(s, 0):.2f} | {total.get(s, 0):.2f} |")
    lines.append(f"| **Total** | **{sum(tagged.values()):.2f}** | **{sum(total.values()):.2f}** |")
    if not tagged:
        lines += ["", "No tagged costs yet: activate the cost allocation tag 'Project' in the Billing console "
                      "and allow about a day for the data."]
    text = "\n".join(lines)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e3_measured.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
