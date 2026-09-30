"""Pre-warm the detector Lambda so the first telemetry messages don't queue behind a cold start.

    python -m tools.warm [--stage local]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from botocore.config import Config

from common.awsenv import session, stack_outputs


def warm_up(sess, function: str, concurrency: int = 1) -> float:
    """Invoke the detector synchronously, `concurrency` calls at once, so that many containers
    are started before telemetry arrives (like provisioned concurrency). Returns seconds taken."""
    client = sess.client("lambda", config=Config(read_timeout=300, retries={"max_attempts": 0},
                                                 max_pool_connections=max(10, concurrency)))

    def one(_):
        resp = client.invoke(FunctionName=function, Payload=json.dumps({"warmup": True}).encode())
        body = json.loads(resp["Payload"].read() or b"{}")
        if resp.get("FunctionError") or not body.get("warm"):
            sys.exit(f"Detector Lambda warm-up failed: {body}")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, range(concurrency)))
    return time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", default="local")
    ap.add_argument("--containers", type=int, default=10, help="containers to start at once")
    args = ap.parse_args()
    sess = session(args.stage)
    secs = warm_up(sess, stack_outputs(sess, args.stage)["DetectorFunctionName"], concurrency=args.containers)
    print(f"detector Lambda warm: {args.containers} containers in {secs:.1f} s")


if __name__ == "__main__":
    main()
