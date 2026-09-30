"""The detector Lambda handler, end to end against mocked DynamoDB, EventBridge and SQS."""
import importlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from simulator.runner import load_scenario, run_scenario

ROOT = Path(__file__).resolve().parents[1]
REGION = "ap-south-1"


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    for k, v in {"TELEMETRY_TABLE": "Telemetry", "STATS_TABLE": "IngestStats",
                 "DETECTIONS_TABLE": "Detections", "EVENT_BUS": "dc-bus", "DETECTOR": "d2h"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)

        def table(name, hk, rk=None):
            ks = [{"AttributeName": hk, "KeyType": "HASH"}] + ([{"AttributeName": rk, "KeyType": "RANGE"}] if rk else [])
            ad = [{"AttributeName": a, "AttributeType": "S"} for a in [hk] + ([rk] if rk else [])]
            ddb.create_table(TableName=name, KeySchema=ks, AttributeDefinitions=ad, BillingMode="PAY_PER_REQUEST")

        table("Telemetry", "gw", "ts")
        table("IngestStats", "gw")
        table("Detections", "day", "id")
        ev, sqs = boto3.client("events", region_name=REGION), boto3.client("sqs", region_name=REGION)
        ev.create_event_bus(Name="dc-bus")
        q = sqs.create_queue(QueueName="anomalies")["QueueUrl"]
        arn = sqs.get_queue_attributes(QueueUrl=q, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        ev.put_rule(Name="anom", EventBusName="dc-bus",
                    EventPattern=json.dumps({"detail-type": ["AnomalyDetected"]}))
        ev.put_targets(Rule="anom", EventBusName="dc-bus", Targets=[{"Id": "q", "Arn": arn}])
        sys.path.insert(0, str(ROOT / "lambdas" / "detector"))
        handler = importlib.reload(importlib.import_module("handler"))
        sys.path.pop(0)
        yield ddb, sqs, q, handler


def test_handler_detects_crah_failure_and_publishes(aws):
    ddb, sqs, q, handler = aws
    scn, _ = load_scenario(ROOT / "simulator" / "scenarios" / "crah_fan_failure.yaml")
    scn.duration_s = 1950
    msgs = sorted(run_scenario(scn, apply_actions=False).messages, key=lambda m: (m["ts"], m["gw"]))
    telemetry = ddb.Table("Telemetry")
    for m in msgs:
        telemetry.put_item(Item=json.loads(json.dumps(m), parse_float=Decimal))   # the bridge stores first
        result = handler.handler(m, None)
    assert result["history"] == handler.ENGINE.messages_needed - 1

    got = []
    for _ in range(5):
        for x in sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=10).get("Messages", []):
            got.append(json.loads(x["Body"])["detail"])
    hits = [e for e in got if e["fault_type"] == "crah_fan_failure" and e["target"] == "crah2"]
    assert hits and hits[0]["seq"] <= 185                         # fault at seq 181, confirmed 30 s later
    assert ddb.Table("Detections").scan()["Count"] == len(got)
    stats = ddb.Table("IngestStats").get_item(Key={"gw": "zone2"})["Item"]
    assert stats["msg_count"] == len([m for m in msgs if m["gw"] == "zone2"]) and stats["detections"] >= 1


def test_history_ignores_messages_from_an_earlier_run(aws):
    ddb, _, _, handler = aws
    telemetry = ddb.Table("Telemetry")
    old = {"gw": "zone1", "ts": "2026-01-01T00:00:00.000Z", "seq": 1, "assets": {}}
    telemetry.put_item(Item=old)
    new = {"gw": "zone1", "ts": "2026-12-01T10:00:00.000Z", "seq": 1, "assets": {}}
    assert handler.history(new) == []


def test_history_skips_interleaved_run_and_stops_at_gap(aws):
    ddb, _, _, handler = aws
    telemetry = ddb.Table("Telemetry")
    base = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    iso = lambda s: (base + timedelta(seconds=s)).isoformat(timespec="milliseconds").replace("+00:00", "Z")  # noqa
    for i in range(1, 21):                                   # this run: seq i at 10*i s
        telemetry.put_item(Item={"gw": "zone1", "ts": iso(10 * i), "seq": i, "assets": {}})
    for i in range(500, 530):                                # an earlier fast run, overlapping timestamps
        telemetry.put_item(Item={"gw": "zone1", "ts": iso(3 * (i - 500) + 105.5), "seq": i, "assets": {}})
    telemetry.put_item(Item={"gw": "zone1", "ts": iso(185), "seq": 19, "assets": {}})   # right seq, wrong time
    msg = {"gw": "zone1", "ts": iso(210), "seq": 21, "assets": {}}
    assert [m["seq"] for m in handler.history(msg)] == list(range(13, 21))
    telemetry.delete_item(Key={"gw": "zone1", "ts": iso(170)})           # message 17 lost
    assert [m["seq"] for m in handler.history(msg)] == [18, 19, 20]


def test_warmup_call_touches_nothing(aws):
    ddb, _, _, handler = aws
    assert handler.handler({"warmup": True}, None) == {"warm": True, "detector": "d2h"}
    assert ddb.Table("IngestStats").scan()["Count"] == 0


def test_stats_split_latency_into_parts(aws):
    ddb, _, _, handler = aws
    now = time.time() * 1000.0
    sent = datetime.fromtimestamp((now - 900) / 1000, timezone.utc).isoformat(timespec="milliseconds")
    msg = {"gw": "zone1", "ts": "2026-12-01T10:00:00.000Z", "seq": 1, "assets": {},
           "sent_at": sent.replace("+00:00", "Z"), "bridge_rx_ms": now - 800, "bridge_tx_ms": now - 500}
    handler.handler(msg, None)
    s = ddb.Table("IngestStats").get_item(Key={"gw": "zone1"})["Item"]
    assert s["stamped_count"] == 1 and s["cold_starts"] == 1
    assert 90 <= float(s["to_bridge_sum_ms"]) <= 110 and 290 <= float(s["bridge_sum_ms"]) <= 310
    assert 480 <= float(s["queue_sum_ms"]) <= 700
    assert float(s["latency_sum_ms"]) >= 900 and float(s["handler_sum_ms"]) > 0
    handler.handler(dict(msg, seq=2, ts="2026-12-01T10:00:10.000Z"), None)
    assert ddb.Table("IngestStats").get_item(Key={"gw": "zone1"})["Item"]["cold_starts"] == 1
