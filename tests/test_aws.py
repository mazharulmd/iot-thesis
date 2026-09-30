"""Step 8 tests: real-AWS pieces that can be checked without an AWS account."""
import json
import pathlib
import sys

import aws_cdk as cdk
import boto3
import pytest
from aws_cdk.assertions import Match, Template
from moto import mock_aws

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "infra"))

from experiments.cost_model import estimate_load_test, load_prices, load_usage, monthly  # noqa: E402
from stacks.data_stack import DataStack  # noqa: E402
from stacks.detection_stack import DetectionStack  # noqa: E402
from stacks.foundation_stack import FoundationStack  # noqa: E402
from stacks.iot_stack import TELEMETRY_SQL, IotStack  # noqa: E402
from tools.status import histogram, percentile  # noqa: E402

REGION = "ap-south-1"


@pytest.fixture(scope="module")
def iot_template(tmp_path_factory):
    code = tmp_path_factory.mktemp("det")
    (code / "handler.py").write_text("def handler(e, c):\n    return e\n")
    app = cdk.App()
    found = FoundationStack(app, "F", stage="t")
    data = DataStack(app, "D", stage="t", on_demand=True)
    det = DetectionStack(app, "Det", stage="t", telemetry=data.telemetry, ingest_stats=data.ingest_stats,
                         detections=data.detections, code_dir=code)
    iot = IotStack(app, "I", stage="t", telemetry=data.telemetry, detector=det.function,
                   errors_bucket=found.artifacts_bucket)
    return Template.from_stack(iot), Template.from_stack(data)


def test_topic_rule_stores_and_invokes_with_timestamps(iot_template):
    iot, _ = iot_template
    assert "FROM 'dc/hall1/+/telemetry'" in TELEMETRY_SQL and "timestamp() AS bridge_rx_ms" in TELEMETRY_SQL
    assert "AS received_at" in TELEMETRY_SQL and "AS ttl" in TELEMETRY_SQL
    iot.has_resource_properties("AWS::IoT::TopicRule", {"TopicRulePayload": {
        "Sql": TELEMETRY_SQL, "AwsIotSqlVersion": "2016-03-23",
        "Actions": [Match.object_like({"DynamoDBv2": Match.any_value()}), Match.object_like({"Lambda": Match.any_value()})],
        "ErrorAction": {"S3": Match.object_like({"Key": "iot-errors/${timestamp()}-${topic(3)}.json"})}}})
    iot.has_resource_properties("AWS::Lambda::Permission", {"Principal": "iot.amazonaws.com"})
    iot.resource_count_is("AWS::IoT::Thing", 5)


def test_device_policy_is_scoped(iot_template):
    iot, _ = iot_template
    doc = json.dumps(iot.find_resources("AWS::IoT::Policy"))
    assert ":client/dc-*" in doc and "topic/dc/hall1/*/telemetry" in doc
    assert "$aws/things/*/shadow/*" in doc and '"iot:*"' not in doc


def test_on_demand_tables(iot_template):
    _, data = iot_template
    tables = data.find_resources("AWS::DynamoDB::Table")
    assert len(tables) == 6 and all(t["Properties"]["BillingMode"] == "PAY_PER_REQUEST" for t in tables.values())


def test_histogram_percentiles():
    item = {"gw": "x", "h25": 70, "h100": 25, "h1000": 4, "hinf": 1, "handler_sum_ms": 5, "hist_sum_ms": 3}
    hist = histogram(item)
    assert hist == {"h25": 70, "h100": 25, "h1000": 4, "hinf": 1}
    assert (percentile(hist, 0.5), percentile(hist, 0.95), percentile(hist, 0.99)) == (25.0, 100.0, 1000.0)
    assert percentile(hist, 1.0) == float("inf") and percentile({}, 0.5) is None


def test_cost_model_scales_and_free_tier():
    p, u = load_prices(), load_usage(pathlib.Path("/nonexistent.json"))
    small, large = monthly(1, p, u), monthly(100, p, u)
    assert small["messages"] == 5 * 30 * 24 * 360 and large["messages"] == 100 * small["messages"]
    assert large["list_total"] == pytest.approx(100 * small["list_total"], rel=0.05)
    assert small["after_free"] < small["list_total"]
    assert small["ddb_provisioned_after_free"] == 0 < large["ddb_provisioned_after_free"]
    assert 0 < estimate_load_test([50, 500, 2000], 30, p, u) < 10


def test_shadows_on_aws_use_the_iot_data_api(monkeypatch):
    from tools.shadow_api import Shadows
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    for k, v in {"AWS_DEFAULT_REGION": REGION, "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        sess = boto3.Session(region_name=REGION)
        sh = Shadows("dev", sess)
        sh.iot = sess.client("iot-data")          # moto only serves the generic data endpoint
        for gw in ("zone1", "zone2", "zone3", "zone4", "plant"):
            sess.client("iot").create_thing(thingName=gw)
        sh.reset()
        res = sh.send("crah1", {"fan_pct": 70}, wait=False)
        doc = json.loads(sh.iot.get_thing_shadow(thingName="zone1")["payload"].read())
        assert doc["state"]["desired"]["crah1"] == {"fan_pct": 70} and doc["state"]["desired"]["cmd_id"] == res["cmd_id"]
        sh.iot.update_thing_shadow(thingName="zone1", payload=json.dumps(
            {"state": {"reported": {"crah1": {"fan_pct": 70}, "cmd_id": res["cmd_id"]}}}).encode())
        done = sh.wait(res, timeout=2)
        assert done["ok"] and done["round_trip_ms"] >= 0


def test_device_certificate_create_and_delete(tmp_path, monkeypatch):
    from tools.aws_devices import create, delete
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    for k, v in {"AWS_DEFAULT_REGION": REGION, "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        sess = boto3.Session(region_name=REGION)
        sess.client("iot").create_policy(policyName="p", policyDocument=json.dumps(
            {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "iot:Connect", "Resource": "*"}]}))
        meta = create(sess, "p", tmp_path, fetch_ca=lambda: "CA")
        assert (tmp_path / "private.pem.key").stat().st_mode & 0o077 == 0
        assert (tmp_path / "endpoint.txt").read_text().strip() == meta["endpoint"]
        assert sess.client("iot").list_attached_policies(target=meta["certificateArn"])["policies"]
        assert delete(sess, tmp_path) == meta["certificateId"]
        assert not list(tmp_path.iterdir())


def test_loadgen_summary_and_extrapolation():
    from tools.loadgen import summary
    row = {"devices": 2000, "sent_per_s": 200.0, "processed_per_s": 199.5, "loss_pct": 0.1, "p50_ms": 150.0,
           "p95_ms": 300.0, "p99_ms": 500.0, "gateway_to_iot_ms": 40.0, "iot_to_lambda_ms": 30.0, "handler_ms": 45.0,
           "lambda_duration_p95_ms": 80.0, "lambda_concurrency_max": 9.0, "lambda_throttles": 0.0,
           "ddb_write_throttles": 0.0, "iot_rule_failures": 0.0, "lambda_duration_avg_ms": 50.0}
    text = summary([row], 10)
    assert "| 2,000 | 200.0 | 199.5 | 0.1 % | 150 | 300 | 500 |" in text
    assert "needs about 50 concurrent executions" in text and "this account allows 10" in text
