"""Send one command through the device shadow and wait for the device to report it.

    python -m tools.send_command crah1 '{"fan_pct": 70}'
    python -m tools.send_command crah1 '{"fan_mode": "auto", "fan_pct": null}'

The remediation Lambda sends the same desired state automatically (Step 5).
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from common.topology import gateway_of, shadow_topic


def send(asset: str, desired: dict, host: str = "127.0.0.1", port: int = 1883,
         timeout: float = 15.0) -> dict:
    gw = gateway_of(asset)
    cmd_id = f"manual-{uuid.uuid4().hex[:8]}"
    done = threading.Event()
    result: dict = {"asset": asset, "gw": gw, "cmd_id": cmd_id, "ok": False}

    def on_connect(c, u, f, rc, p):
        c.subscribe(shadow_topic(gw), qos=1)       # the device reports on the update topic
        payload = {"state": {"desired": {asset: desired, "cmd_id": cmd_id,
                                         "issued_at": datetime.now(timezone.utc).isoformat()}}}
        result["sent"] = time.time()
        c.publish(shadow_topic(gw), json.dumps(payload), qos=1)

    def on_message(c, u, msg):
        reported = json.loads(msg.payload).get("state", {}).get("reported", {})
        if reported.get("cmd_id") == cmd_id:
            result.update(ok=asset in reported and "errors" not in reported,
                          reported=reported, round_trip_ms=round((time.time() - result["sent"]) * 1000, 1))
            done.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"cli-{cmd_id}")
    client.on_connect, client.on_message = on_connect, on_message
    client.connect(host, port)
    client.loop_start()
    done.wait(timeout)
    client.loop_stop()
    client.disconnect()
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Send a command via the device shadow")
    ap.add_argument("asset")
    ap.add_argument("desired", help='JSON, e.g. \'{"fan_pct": 70}\'')
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()
    res = send(args.asset, json.loads(args.desired), args.host, args.port)
    print(json.dumps({k: v for k, v in res.items() if k != "sent"}, indent=2))
    if "reported" not in res:
        print("No report from the device within 15 s. Is the live simulator running? "
              "(make pipeline-up). The command stays pending and is applied when it connects.")
    raise SystemExit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
