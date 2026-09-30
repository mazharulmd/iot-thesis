"""Device-shadow operations from the cloud side, for the checks and tools.

Locally the shadows live in the bridge and are reached over MQTT; on AWS they live in IoT Core and
are reached through the IoT data API (the same call the remediation Lambda makes).
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from common.topology import GATEWAYS, gateway_of

from .reset_shadows import reset as reset_local
from .send_command import send as send_local


class Shadows:
    def __init__(self, stage: str, sess=None):
        self.stage = stage
        self.iot = None
        if stage != "local":
            host = sess.client("iot").describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
            self.iot = sess.client("iot-data", endpoint_url=f"https://{host}")

    def reset(self) -> None:
        """Clear desired and reported state of every gateway (commands of earlier runs cannot leak)."""
        if self.iot is None:
            reset_local()
            return
        body = json.dumps({"state": {"desired": None, "reported": None}}).encode()
        for gw in GATEWAYS:
            self.iot.update_thing_shadow(thingName=gw, payload=body)

    def send(self, asset: str, desired: dict, wait: bool = True, timeout: float = 15.0) -> dict:
        """Write desired state for one asset; with wait=True, until the gateway reports it applied."""
        if self.iot is None:
            return send_local(asset, desired, timeout=timeout)
        gw = gateway_of(asset)
        cmd_id = f"check-{uuid.uuid4().hex[:8]}"
        issued = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        t0 = time.time()
        self.iot.update_thing_shadow(thingName=gw, payload=json.dumps(
            {"state": {"desired": {asset: desired, "cmd_id": cmd_id, "issued_at": issued}}}).encode())
        result = {"asset": asset, "gw": gw, "cmd_id": cmd_id, "ok": False, "sent": t0}
        return self.wait(result, timeout) if wait else result

    def wait(self, result: dict, timeout: float = 30.0) -> dict:
        """Poll the shadow until the gateway reported the command (by cmd_id)."""
        if self.iot is None:
            raise RuntimeError("wait() is for the AWS stage; locally send() waits over MQTT")
        deadline = time.time() + timeout
        while time.time() < deadline:
            doc = json.loads(self.iot.get_thing_shadow(thingName=result["gw"])["payload"].read())
            reported = doc.get("state", {}).get("reported", {})
            if reported.get("cmd_id") == result["cmd_id"]:
                return {**result, "ok": result["asset"] in reported and "errors" not in reported,
                        "reported": reported, "round_trip_ms": round((time.time() - result["sent"]) * 1000, 1)}
            time.sleep(0.2)
        return result
