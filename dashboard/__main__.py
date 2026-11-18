"""Live control-room dashboard.

    python -m dashboard                         offline simulation, nothing else needed  (make dashboard)
    python -m dashboard --stage local           a running LocalStack stack              (make dashboard-local)
    python -m dashboard --stage dev             the stack deployed on AWS               (make dashboard-aws)

Open http://localhost:8080. In the simulation, inject faults from the page and watch them being
detected, remediated and verified; high-risk plans wait for you to approve them. With --host 0.0.0.0
(for example on an EC2 instance) the page needs the access token printed at start-up.
"""
from __future__ import annotations

import argparse
import secrets
import sys

from .core import LiveState
from .server import serve


def main() -> None:
    ap = argparse.ArgumentParser(description="Live dashboard for dc-selfheal")
    ap.add_argument("--stage", help="show a deployed stack (local = LocalStack, dev = AWS); default: simulation")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--speed", type=float, default=10.0, help="simulation: simulated seconds per second")
    ap.add_argument("--seed", type=int, default=7, help="simulation: random seed of the hall")
    ap.add_argument("--detector", default="d2h", help="simulation: detector (d0, d1, d2, d1h, d2h)")
    ap.add_argument("--interval", type=float, default=3.0, help="AWS: seconds between polls")
    ap.add_argument("--token", help="access token (generated when --host is not localhost)")
    args = ap.parse_args()

    if args.stage:
        from .aws import AwsSource
        state = LiveState("aws", title=f"Live: stack {args.stage}")
        source = AwsSource(state, args.stage, args.interval)
    else:
        from .sim import SimulationSource
        state = LiveState("simulation", title="Simulated data hall")
        source = SimulationSource(state, speed=args.speed, detector=args.detector, seed=args.seed)

    local = args.host in ("127.0.0.1", "localhost", "::1")
    token = args.token or (None if local else secrets.token_urlsafe(18))
    httpd = serve(state, source, args.host, args.port, token)
    source.start()
    shown = "localhost" if local or args.host == "0.0.0.0" else args.host
    url = f"http://{shown}:{args.port}/" + (f"?token={token}" if token else "")
    print(f"dashboard: {url}" + ("" if local else "   (use the server's public address instead of localhost)"),
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        source.stop()
        httpd.server_close()
    sys.exit(0)


if __name__ == "__main__":
    main()
