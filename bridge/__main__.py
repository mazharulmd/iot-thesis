"""Run the bridge:  python -m bridge --stage local

Discovers table, function and bucket names from the CloudFormation stacks on
LocalStack, subscribes to telemetry and shadow topics, and applies the rules.
"""
from __future__ import annotations

import argparse
import json
import logging
import queue
import signal
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

from common.awsenv import session as aws_session
from common.awsenv import stack_outputs
from common.topology import SHADOW_GET_FILTER, SHADOW_UPDATE_FILTER, TELEMETRY_FILTER, gateway_from_topic

from .core import BridgeCore

log = logging.getLogger("bridge")
STATE_FILE = Path(".bridge/shadows.json")


def poll_shadow_queue(sqs, url: str, inbox: queue.Queue, stop: threading.Event) -> None:
    """Shadow updates from the cloud side (the remediation Lambda) arrive on an SQS queue locally;
    on AWS the Lambda calls IoT Core's UpdateThingShadow instead."""
    while not stop.is_set():
        try:
            msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=5).get("Messages", [])
        except Exception as exc:  # noqa: BLE001 - keep polling
            log.warning("shadow queue: %s", exc)
            time.sleep(2)
            continue
        for m in msgs:
            try:
                body = json.loads(m["Body"])
                inbox.put((f"queue:{body['thing']}", json.dumps(body["payload"]).encode()))
            except (KeyError, json.JSONDecodeError) as exc:
                log.warning("bad shadow queue message: %s", exc)
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])


class GatewayWorkers:
    """One worker thread per gateway: gateways are handled in parallel, each gateway in order."""

    def __init__(self, core: BridgeCore):
        self.core = core
        self.queues: dict[str, queue.Queue] = {}

    def submit(self, gw: str, payload: bytes, rx_ms: float) -> None:
        q = self.queues.get(gw)
        if q is None:
            q = self.queues[gw] = queue.Queue()
            threading.Thread(target=self._run, args=(q,), name=f"rules-{gw}", daemon=True).start()
        q.put((payload, rx_ms))

    def _run(self, q: queue.Queue) -> None:
        while True:
            payload, rx_ms = q.get()
            try:
                self.core.on_telemetry(payload, rx_ms)
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("telemetry rule failed")

    def backlog(self) -> int:
        return sum(q.qsize() for q in self.queues.values())


def main() -> None:
    ap = argparse.ArgumentParser(description="Local IoT rules + shadow bridge")
    ap.add_argument("--stage", default="local")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--no-detector", action="store_true", help="store telemetry only")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    session = aws_session(args.stage)
    outputs = stack_outputs(session, args.stage)
    function = outputs.get("DetectorFunctionName") or outputs.get("IngestFunctionName")
    log.info("using table=%s function=%s bucket=%s", outputs["TelemetryTableName"],
             function, outputs.get("ArtifactsBucketName"))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bridge", protocol=mqtt.MQTTv311)
    inbox: queue.Queue = queue.Queue()
    core = BridgeCore(
        dynamodb=session.resource("dynamodb"),
        lambda_client=session.client("lambda"),
        s3_client=session.client("s3"),
        telemetry_table=outputs["TelemetryTableName"],
        detector_function=None if args.no_detector else function,
        errors_bucket=outputs.get("ArtifactsBucketName"),
        publish=lambda topic, body: client.publish(topic, body, qos=1),
    )

    if STATE_FILE.exists():
        try:
            core.shadows.docs = json.loads(STATE_FILE.read_text())
            log.info("reloaded %d shadow documents from %s", len(core.shadows.docs), STATE_FILE)
        except json.JSONDecodeError:
            log.warning("ignoring unreadable %s", STATE_FILE)

    def on_connect(c, userdata, flags, reason_code, properties):
        c.subscribe([(TELEMETRY_FILTER, 1), (SHADOW_UPDATE_FILTER, 1), (SHADOW_GET_FILTER, 1)])
        log.info("connected to MQTT %s:%s", args.host, args.port)

    client.on_connect = on_connect
    workers = GatewayWorkers(core)

    def on_message(c, userdata, msg):
        if msg.topic.endswith("/telemetry"):              # rules run off the MQTT thread, per gateway
            workers.submit(gateway_from_topic(msg.topic), msg.payload, time.time() * 1000.0)
        else:
            inbox.put((msg.topic, msg.payload))

    client.on_message = on_message
    client.reconnect_delay_set(1, 30)
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if outputs.get("ShadowQueueUrl"):
        threading.Thread(target=poll_shadow_queue, args=(session.client("sqs"), outputs["ShadowQueueUrl"], inbox, stop),
                         name="shadow-queue", daemon=True).start()
        log.info("reading cloud shadow updates from %s", outputs["ShadowQueueUrl"])

    last_report = time.time()
    STATE_FILE.parent.mkdir(exist_ok=True)
    while not stop.is_set():
        try:
            topic, payload = inbox.get(timeout=1.0)
        except queue.Empty:
            topic = None
        if topic and topic.startswith("queue:"):
            thing = topic.split(":", 1)[1]
            log.info("shadow update from cloud for %s: %s", thing, payload.decode()[:300])
            core.on_shadow_update(thing, payload)
            STATE_FILE.write_text(json.dumps(core.shadows.docs, indent=2))
        elif topic and topic.endswith("/shadow/get"):
            core.on_shadow_get(gateway_from_topic(topic))
        elif topic and topic.endswith("/shadow/update"):
            core.on_shadow_update(gateway_from_topic(topic), payload)
            STATE_FILE.write_text(json.dumps(core.shadows.docs, indent=2))
        if time.time() - last_report > 60:
            log.info("stats %s backlog=%d", core.stats, workers.backlog())
            last_report = time.time()

    client.loop_stop()
    client.disconnect()
    log.info("stopped; stats %s", core.stats)


if __name__ == "__main__":
    main()
