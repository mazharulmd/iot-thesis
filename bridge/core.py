"""The bridge's rules, independent of MQTT so they can be unit tested.

Rule 1  telemetry -> DynamoDB Telemetry table (30-day TTL)
Rule 2  telemetry -> detector Lambda (asynchronous invoke), stamped with bridge_rx_ms / bridge_tx_ms
        (like `timestamp()` in an IoT rule) so the Lambda can split latency into its parts

on_telemetry is thread-safe (it uses low-level clients), so the runner can process gateways in
parallel the way IoT Core runs rule actions in parallel.
Error   any failure -> S3 artifacts bucket under iot-errors/
Shadow  update topic -> shadow document -> delta topic
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from common.topology import shadow_get_topic, shadow_topic

from .shadow import ShadowStore, compute_delta

log = logging.getLogger("bridge")
TTL_DAYS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class BridgeCore:
    def __init__(self, *, dynamodb, lambda_client, s3_client, telemetry_table: str,
                 detector_function: str | None, errors_bucket: str | None,
                 publish: Callable[[str, str], None]):
        self.ddb = dynamodb.meta.client          # clients are thread-safe, resources are not
        self.table_name = telemetry_table
        self.lambda_client = lambda_client
        self.s3 = s3_client
        self.detector_function = detector_function
        self.errors_bucket = errors_bucket
        self.publish = publish
        self.shadows = ShadowStore()
        self.stats = {"telemetry": 0, "stored": 0, "invoked": 0, "errors": 0, "shadow_updates": 0,
                      "deltas": 0}

    # ------------------------------------------------------------------ telemetry
    def on_telemetry(self, payload: bytes, rx_ms: float | None = None) -> None:
        rx_ms = rx_ms if rx_ms is not None else time.time() * 1000.0
        self.stats["telemetry"] += 1
        try:
            msg = json.loads(payload)
            msg["received_at"] = _now_iso()
        except json.JSONDecodeError as exc:
            self._archive_error("bad-json", payload.decode(errors="replace"), exc)
            return
        try:
            item = json.loads(json.dumps(msg), parse_float=Decimal)
            item["ttl"] = int(time.time()) + TTL_DAYS * 86400
            self.ddb.put_item(TableName=self.table_name, Item=item)   # resource client: plain values
            self.stats["stored"] += 1
        except Exception as exc:  # noqa: BLE001 - every failure goes to the error archive
            self._archive_error(f"{msg.get('gw')}-{msg.get('seq')}-store", msg, exc)
        if self.detector_function:
            try:
                stamped = dict(msg, bridge_rx_ms=round(rx_ms, 1), bridge_tx_ms=round(time.time() * 1000.0, 1))
                self.lambda_client.invoke(FunctionName=self.detector_function,
                                          InvocationType="Event", Payload=json.dumps(stamped).encode())
                self.stats["invoked"] += 1
            except Exception as exc:  # noqa: BLE001
                self._archive_error(f"{msg.get('gw')}-{msg.get('seq')}-invoke", msg, exc)

    def _archive_error(self, name: str, payload, exc: Exception) -> None:
        self.stats["errors"] += 1
        log.warning("rule error %s: %s", name, exc)
        if not self.errors_bucket:
            return
        key = f"iot-errors/{datetime.now(timezone.utc):%Y/%m/%d}/{name}-{int(time.time() * 1000)}.json"
        body = json.dumps({"error": repr(exc), "payload": payload}, default=str)
        try:
            self.s3.put_object(Bucket=self.errors_bucket, Key=key, Body=body.encode())
        except Exception as exc2:  # noqa: BLE001
            log.error("could not archive error: %s", exc2)

    # ------------------------------------------------------------------ shadows
    def on_shadow_update(self, thing: str, payload: bytes) -> None:
        try:
            state = json.loads(payload).get("state", {})
        except json.JSONDecodeError:
            return
        self.stats["shadow_updates"] += 1
        doc, delta = self.shadows.update(thing, state)
        self.publish(shadow_topic(thing, "accepted"),
                     json.dumps({"state": state, "version": doc["version"], "timestamp": doc["timestamp"]}))
        if "desired" in state and delta:
            self.stats["deltas"] += 1
            self.publish(shadow_topic(thing, "delta"),
                         json.dumps({"state": delta, "version": doc["version"], "timestamp": doc["timestamp"]}))

    def on_shadow_get(self, thing: str) -> None:
        """Answer a device's request for its shadow, including any pending delta."""
        doc = self.shadows.get(thing)
        state = {"desired": doc["desired"], "reported": doc["reported"]}
        delta = compute_delta(doc["desired"], doc["reported"])
        if delta:
            state["delta"] = delta
        self.publish(shadow_get_topic(thing, "accepted"),
                     json.dumps({"state": state, "version": doc["version"],
                                 "timestamp": doc.get("timestamp", int(time.time()))}))
