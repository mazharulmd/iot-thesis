"""Show AnomalyDetected events from the anomaly queue.

    python -m tools.events            # print and remove waiting events
    python -m tools.events --follow   # keep watching (Ctrl-C to stop)
"""
from __future__ import annotations

import argparse
import json
import time

from common.awsenv import session, stack_outputs


def drain(sqs, url: str, wait: int = 1) -> list[dict]:
    out = []
    while True:
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=wait).get("Messages", [])
        if not msgs:
            return out
        for m in msgs:
            out.append(json.loads(m["Body"])["detail"])
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])


def fmt(e: dict) -> str:
    return (f"{e['ts']}  {e['fault_type']:22s} target={e['target']:8s} asset={e['asset']:8s} "
            f"risk={e['risk']:6s} playbook={e['playbook']:22s} evidence={json.dumps(e.get('evidence', {}))}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Show anomaly events")
    ap.add_argument("--stage", default="local")
    ap.add_argument("--follow", action="store_true")
    args = ap.parse_args()
    sess = session(args.stage)
    url = stack_outputs(sess, args.stage)["AnomalyQueueUrl"]
    sqs = sess.client("sqs")
    while True:
        for e in sorted(drain(sqs, url), key=lambda e: e["ts"]):
            print(fmt(e), flush=True)
        if not args.follow:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
