"""Step 3 unit tests: topology, shadow logic, bridge rules, ingest Lambda."""
import json
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from bridge.core import BridgeCore
from bridge.shadow import ShadowStore, compute_delta, merge
from common.topology import gateway_from_topic, gateway_of, shadow_topic, telemetry_topic

REGION = "ap-south-1"


# ---------------------------------------------------------------- topology
@pytest.mark.parametrize("asset,gw", [
    ("rack01", "zone1"), ("rack05", "zone1"), ("rack06", "zone2"), ("rack20", "zone4"),
    ("crah3", "zone3"), ("pdu4", "zone4"), ("crah5", "plant"), ("pump2", "plant"),
    ("chiller", "plant"), ("ups1", "plant"),
])
def test_gateway_of(asset, gw):
    assert gateway_of(asset) == gw


def test_topics_round_trip():
    assert gateway_from_topic(telemetry_topic("zone2")) == "zone2"
    assert gateway_from_topic(shadow_topic("plant")) == "plant"
    assert shadow_topic("zone1", "delta") == "$aws/things/zone1/shadow/update/delta"


# ---------------------------------------------------------------- shadows
def test_delta_only_contains_differences():
    desired = {"crah1": {"fan_pct": 80, "status": "on"}, "cmd_id": "a"}
    reported = {"crah1": {"fan_pct": 80.0, "status": "off"}, "cmd_id": "a"}
    assert compute_delta(desired, reported) == {"crah1": {"status": "on"}}


def test_merge_none_deletes():
    assert merge({"a": 1, "b": {"c": 2}}, {"a": None, "b": {"d": 3}}) == {"b": {"c": 2, "d": 3}}


def test_shadow_delta_clears_when_device_reports():
    store = ShadowStore()
    _, delta = store.update("zone1", {"desired": {"crah1": {"fan_pct": 70}, "cmd_id": "x"}})
    assert delta == {"crah1": {"fan_pct": 70}, "cmd_id": "x"}
    doc, delta = store.update("zone1", {"reported": {"crah1": {"fan_pct": 70.0}, "cmd_id": "x"}})
    assert delta == {} and doc["version"] == 2


# ---------------------------------------------------------------- bridge rules
class FakeLambda:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def invoke(self, **kw):
        if self.fail:
            raise RuntimeError("lambda down")
        self.calls.append(kw)


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.create_table(TableName="Telemetry",
                         KeySchema=[{"AttributeName": "gw", "KeyType": "HASH"},
                                    {"AttributeName": "ts", "KeyType": "RANGE"}],
                         AttributeDefinitions=[{"AttributeName": "gw", "AttributeType": "S"},
                                               {"AttributeName": "ts", "AttributeType": "S"}],
                         BillingMode="PAY_PER_REQUEST")
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="artifacts", CreateBucketConfiguration={"LocationConstraint": REGION})
        yield ddb, s3


def make_core(aws, lam=None):
    ddb, s3 = aws
    published = []
    core = BridgeCore(dynamodb=ddb, lambda_client=lam or FakeLambda(), s3_client=s3,
                      telemetry_table="Telemetry", detector_function="detector",
                      errors_bucket="artifacts", publish=lambda t, b: published.append((t, json.loads(b))))
    return core, published


MSG = {"gw": "zone2", "ts": "2026-12-01T10:00:00.000Z", "seq": 7, "sent_at": "2026-12-01T10:00:00.010Z",
       "assets": {"rack07": {"t_in": 20.61, "p_kw": 40.2}, "crah2": {"status": "on", "fan_pct": 62.5}}}


def test_telemetry_is_stored_with_ttl_and_sent_to_detector(aws):
    core, _ = make_core(aws)
    core.on_telemetry(json.dumps(MSG).encode())
    item = aws[0].Table("Telemetry").get_item(Key={"gw": "zone2", "ts": MSG["ts"]})["Item"]
    assert item["assets"]["rack07"]["t_in"] == Decimal("20.61")
    assert item["ttl"] > 0 and "received_at" in item
    assert core.lambda_client.calls[0]["InvocationType"] == "Event"
    sent = json.loads(core.lambda_client.calls[0]["Payload"])
    assert sent["seq"] == 7 and sent["bridge_tx_ms"] >= sent["bridge_rx_ms"] > 0


def test_gateway_workers_parallel_but_ordered_per_gateway():
    import threading
    import time as _time

    from bridge.__main__ import GatewayWorkers

    seen, lock = [], threading.Lock()

    class SlowCore:
        def on_telemetry(self, payload, rx_ms):
            _time.sleep(0.05)
            with lock:
                seen.append(json.loads(payload))

    workers = GatewayWorkers(SlowCore())
    t0 = _time.time()
    for seq in range(4):
        for gw in ("zone1", "zone2", "zone3", "zone4", "plant"):
            workers.submit(gw, json.dumps({"gw": gw, "seq": seq}).encode(), 0.0)
    while len(seen) < 20 and _time.time() - t0 < 5:
        _time.sleep(0.01)
    assert len(seen) == 20
    assert _time.time() - t0 < 0.6                     # 5 gateways in parallel: ~0.2 s, serial would be 1 s
    for gw in ("zone1", "plant"):
        assert [m["seq"] for m in seen if m["gw"] == gw] == [0, 1, 2, 3]


def test_rule_errors_go_to_s3(aws):
    core, _ = make_core(aws, FakeLambda(fail=True))
    core.on_telemetry(json.dumps(MSG).encode())
    core.on_telemetry(b"not json")
    keys = [o["Key"] for o in aws[1].list_objects_v2(Bucket="artifacts")["Contents"]]
    assert len(keys) == 2 and all(k.startswith("iot-errors/") for k in keys)
    assert core.stats["errors"] == 2 and core.stats["stored"] == 1


def test_bridge_publishes_delta_for_desired_only(aws):
    core, published = make_core(aws)
    core.on_shadow_update("zone1", json.dumps({"state": {"desired": {"crah1": {"fan_pct": 70}}}}).encode())
    core.on_shadow_update("zone1", json.dumps({"state": {"reported": {"crah1": {"fan_pct": 70}}}}).encode())
    deltas = [p for t, p in published if t.endswith("/delta")]
    assert len(deltas) == 1 and deltas[0]["state"] == {"crah1": {"fan_pct": 70}}


def test_shadow_get_returns_pending_delta(aws):
    core, published = make_core(aws)
    core.on_shadow_update("zone2", json.dumps({"state": {"desired": {"crah2": {"fan_pct": 65}}}}).encode())
    core.on_shadow_get("zone2")
    topic, body = published[-1]
    assert topic == "$aws/things/zone2/shadow/get/accepted"
    assert body["state"]["delta"] == {"crah2": {"fan_pct": 65}}


def test_shadow_get_without_pending_has_no_delta(aws):
    core, published = make_core(aws)
    core.on_shadow_get("zone3")
    assert "delta" not in published[-1][1]["state"]


def test_null_section_clears_shadow():
    store = ShadowStore()
    store.update("zone1", {"desired": {"crah1": {"fan_pct": 70}}, "reported": {"crah1": {"fan_pct": 70}}})
    doc, delta = store.update("zone1", {"desired": None, "reported": None})
    assert doc["desired"] == {} and doc["reported"] == {} and delta == {}
