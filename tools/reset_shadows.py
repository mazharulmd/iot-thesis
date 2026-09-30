"""Clear desired and reported state of every gateway shadow.

Used before each run so commands from an earlier run cannot leak into a new one.

    python -m tools.reset_shadows
"""
from __future__ import annotations

import argparse
import json
import time

import paho.mqtt.client as mqtt

from common.topology import GATEWAYS, shadow_topic


def reset(host: str = "127.0.0.1", port: int = 1883) -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"reset-{int(time.time())}")
    client.connect(host, port)
    client.loop_start()
    body = json.dumps({"state": {"desired": None, "reported": None}})
    infos = [client.publish(shadow_topic(gw), body, qos=1) for gw in GATEWAYS]
    for info in infos:
        info.wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description="Reset all gateway shadows")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()
    reset(args.host, args.port)
    print(f"cleared shadows for {', '.join(GATEWAYS)}")


if __name__ == "__main__":
    main()
