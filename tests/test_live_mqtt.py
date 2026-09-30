"""Integration test: live simulator <-> MQTT broker <-> bridge rules and shadows.

Needs an MQTT broker on 127.0.0.1:1883 (make up). Skipped otherwise, and skipped
while the background pipeline runs so it never interferes with it.
"""
import json
import socket
import threading
import time
from pathlib import Path

import boto3
import paho.mqtt.client as mqtt
import pytest
from moto import mock_aws

from bridge.core import BridgeCore
from common.topology import (GATEWAYS, SHADOW_GET_FILTER, SHADOW_UPDATE_FILTER, TELEMETRY_FILTER,
                             gateway_from_topic)
from simulator.config import ScenarioConfig
from simulator.live import LiveSimulator
from tools.send_command import send


def _broker_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 1883), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not _broker_up(), reason="no MQTT broker on 127.0.0.1:1883 (run: make up)"),
    pytest.mark.skipif(Path(".run/bridge.pid").exists(), reason="background pipeline is running"),
]


class LiveBridge:
    """Bridge rules + shadow service on a real MQTT connection, storage mocked with moto."""

    def __init__(self, ddb):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"test-bridge-{time.time()}")
        self.core = BridgeCore(dynamodb=ddb, lambda_client=None, s3_client=None, telemetry_table="Telemetry",
                               detector_function=None, errors_bucket=None,
                               publish=lambda t, b: self.client.publish(t, b, qos=1))
        self.lock = threading.Lock()
        self.client.on_connect = lambda c, *a: c.subscribe(
            [(TELEMETRY_FILTER, 1), (SHADOW_UPDATE_FILTER, 1), (SHADOW_GET_FILTER, 1)])
        self.client.on_message = self._on_message
        self.client.connect("127.0.0.1", 1883)
        self.client.loop_start()
        time.sleep(0.5)

    def _on_message(self, c, u, msg):
        with self.lock:
            gw = gateway_from_topic(msg.topic)
            if msg.topic.endswith("/telemetry"):
                self.core.on_telemetry(msg.payload)
            elif msg.topic.endswith("/shadow/get"):
                self.core.on_shadow_get(gw)
            else:
                self.core.on_shadow_update(gw, msg.payload)

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()


def make_table():
    ddb = boto3.resource("dynamodb", region_name="ap-south-1")
    ddb.create_table(TableName="Telemetry",
                     KeySchema=[{"AttributeName": "gw", "KeyType": "HASH"},
                                {"AttributeName": "ts", "KeyType": "RANGE"}],
                     AttributeDefinitions=[{"AttributeName": "gw", "AttributeType": "S"},
                                           {"AttributeName": "ts", "AttributeType": "S"}],
                     BillingMode="PAY_PER_REQUEST")
    return ddb


def test_live_pipeline_round_trip(tmp_path):
    with mock_aws():
        ddb = make_table()
        bridge = LiveBridge(ddb)
        core = bridge.core
        sim = LiveSimulator(ScenarioConfig(name="it", duration_s=300, warmup_s=60), speed=50,
                            out_dir=tmp_path, client_prefix="test-")
        runner = threading.Thread(target=sim.run, args=(300,))
        runner.start()
        time.sleep(2)
        result = send("crah1", {"fan_pct": 75})
        runner.join(timeout=30)
        time.sleep(0.5)
        bridge.stop()

        assert result["ok"], result
        assert result["round_trip_ms"] < 2000
        assert sim.hall.crahs[0].fan_mode == "manual" and sim.hall.crahs[0].fan_manual_pct == 75
        table = ddb.Table("Telemetry")
        for gw in GATEWAYS:
            n = table.query(KeyConditionExpression="gw = :g", ExpressionAttributeValues={":g": gw})["Count"]
            assert n >= 25, f"{gw}: only {n} messages stored"
        labels = json.loads((tmp_path / "labels.json").read_text())
        assert labels["published_messages"] >= 150
        assert core.stats["errors"] == 0


def test_command_sent_while_offline_is_applied_on_connect(tmp_path):
    """The race seen on the server: command sent before the gateways had connected."""
    with mock_aws():
        bridge = LiveBridge(make_table())
        pending = threading.Thread(target=send, args=("crah2", {"fan_pct": 65}), kwargs={"timeout": 20})
        pending.start()
        time.sleep(1.0)                      # command is now waiting in the shadow
        sim = LiveSimulator(ScenarioConfig(name="offline", duration_s=120, warmup_s=60), speed=50,
                            out_dir=tmp_path, client_prefix="test-")
        runner = threading.Thread(target=sim.run, args=(120,))
        runner.start()
        runner.join(timeout=30)
        pending.join(timeout=25)
        bridge.stop()
        assert sim.hall.crahs[1].fan_mode == "manual" and sim.hall.crahs[1].fan_manual_pct == 65
        assert len(sim.commands_log) == 1
