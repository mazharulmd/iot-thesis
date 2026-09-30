"""CDK assertions for the Data and Detection stacks."""
import pathlib
import sys

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "infra"))

from stacks.data_stack import DataStack  # noqa: E402
from stacks.detection_stack import DetectionStack  # noqa: E402
from stacks.foundation_stack import FoundationStack  # noqa: E402
from stacks.remediation_stack import RemediationStack  # noqa: E402


@pytest.fixture(scope="module")
def templates(tmp_path_factory):
    code = tmp_path_factory.mktemp("detector")
    (code / "handler.py").write_text("def handler(e, c):\n    return e\n")
    app = cdk.App()
    data = DataStack(app, "Data", stage="test")
    det = DetectionStack(app, "Detection", stage="test", telemetry=data.telemetry,
                         ingest_stats=data.ingest_stats, detections=data.detections, code_dir=code)
    return Template.from_stack(data), Template.from_stack(det)


def test_telemetry_table_has_ttl_and_keys(templates):
    data, _ = templates
    data.has_resource_properties("AWS::DynamoDB::Table", {
        "KeySchema": [{"AttributeName": "gw", "KeyType": "HASH"}, {"AttributeName": "ts", "KeyType": "RANGE"}],
        "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
    })


def test_capacity_stays_in_always_free_tier(templates):
    data, _ = templates
    tables = data.find_resources("AWS::DynamoDB::Table")
    assert len(tables) == 6
    wcu = sum(t["Properties"]["ProvisionedThroughput"]["WriteCapacityUnits"] for t in tables.values())
    rcu = sum(t["Properties"]["ProvisionedThroughput"]["ReadCapacityUnits"] for t in tables.values())
    assert wcu <= 25 and rcu <= 25


def test_detector_lambda_config(templates):
    _, det = templates
    det.has_resource_properties("AWS::Lambda::Function", {
        "Runtime": "python3.12",
        "Handler": "handler.handler",
        "MemorySize": 512,
        "Environment": {"Variables": {
            "DETECTOR": "d2h", "TELEMETRY_TABLE": Match.any_value(), "STATS_TABLE": Match.any_value(),
            "DETECTIONS_TABLE": Match.any_value(), "EVENT_BUS": Match.any_value()}},
    })
    det.resource_count_is("Custom::LogRetention", 0)


def test_anomalies_routed_from_bus_to_queue(templates):
    _, det = templates
    det.resource_count_is("AWS::Events::EventBus", 1)
    det.has_resource_properties("AWS::Events::Rule", {
        "EventPattern": {"source": ["dc.selfheal.detector"], "detail-type": ["AnomalyDetected"]},
        "Targets": Match.array_with([Match.object_like({"Arn": Match.any_value()})]),
    })


def test_detector_may_publish_events(templates):
    _, det = templates
    policies = det.find_resources("AWS::IAM::Policy")
    actions = str(policies)
    assert "events:PutEvents" in actions
    assert "dynamodb:Query" in actions


def test_missing_build_gives_clear_error(tmp_path):
    app = cdk.App()
    data = DataStack(app, "Data2", stage="test")
    with pytest.raises(FileNotFoundError, match="make build-lambdas"):
        DetectionStack(app, "Det2", stage="test", telemetry=data.telemetry, ingest_stats=data.ingest_stats,
                       detections=data.detections, code_dir=tmp_path / "nope")


@pytest.fixture(scope="module")
def remediation(tmp_path_factory):
    det_code, rem_code, appr_code = (tmp_path_factory.mktemp(n) for n in ("det", "rem", "appr"))
    for d in (det_code, rem_code, appr_code):
        (d / "handler.py").write_text("def handler(e, c):\n    return e\n")
    app = cdk.App()
    found = FoundationStack(app, "F", stage="test", alert_email=None)
    data = DataStack(app, "D", stage="test")
    det = DetectionStack(app, "Det", stage="test", telemetry=data.telemetry, ingest_stats=data.ingest_stats,
                         detections=data.detections, code_dir=det_code)
    local = RemediationStack(app, "RemLocal", stage="test", telemetry=data.telemetry, incidents=data.incidents,
                             locks=data.locks, guardrails=data.guardrails, bus=det.bus, alerts=found.alerts_topic,
                             shadow_transport="sqs", code_dir=rem_code, approval_code_dir=appr_code)
    aws = RemediationStack(app, "RemAws", stage="test", telemetry=data.telemetry, incidents=data.incidents,
                           locks=data.locks, guardrails=data.guardrails, bus=det.bus, alerts=found.alerts_topic,
                           shadow_transport="iot", code_dir=rem_code, approval_code_dir=appr_code)
    return Template.from_stack(local), Template.from_stack(aws)


def test_playbook_state_machine_is_standard_and_started_by_anomalies(remediation):
    local, _ = remediation
    local.has_resource_properties("AWS::StepFunctions::StateMachine", {"StateMachineType": "STANDARD"})
    local.has_resource_properties("AWS::Events::Rule", {
        "EventPattern": {"source": ["dc.selfheal.detector"], "detail-type": ["AnomalyDetected"]},
        "Targets": Match.array_with([Match.object_like({"InputPath": "$.detail"})]),
    })
    definition = str(local.find_resources("AWS::StepFunctions::StateMachine"))
    for state in ("Open", "Precheck", "RequestApproval", "Act", "WaitForEffect", "Verify", "Close", "Escalate"):
        assert f'\\"{state}\\"' in definition or f'"{state}"' in definition, state


def test_local_edition_sends_shadow_updates_to_a_queue(remediation):
    local, aws = remediation
    local.resource_count_is("AWS::SQS::Queue", 1)
    local.has_resource_properties("AWS::Lambda::Function", {
        "Environment": {"Variables": {"SHADOW_TRANSPORT": "sqs", "SHADOW_QUEUE_URL": Match.any_value(),
                                      "AUTOMATION": "on", "POLL_S": "10"}}})
    aws.resource_count_is("AWS::SQS::Queue", 0)
    aws.has_resource_properties("AWS::Lambda::Function", {"Environment": {"Variables": {"SHADOW_TRANSPORT": "iot"}}})
    assert "iot:UpdateThingShadow" in str(aws.find_resources("AWS::IAM::Policy"))


def test_approval_function_url_and_task_token_wait(remediation):
    local, _ = remediation
    local.has_resource_properties("AWS::Lambda::Url", {"AuthType": "NONE"})
    definition = str(local.find_resources("AWS::StepFunctions::StateMachine"))
    assert "waitForTaskToken" in definition and "TimeoutSeconds" in definition
    policies = str(local.find_resources("AWS::IAM::Policy"))
    assert "states:SendTaskSuccess" in policies
    local.has_resource_properties("AWS::Lambda::Function", {"Environment": {"Variables": {
        "GUARDRAILS_TABLE": Match.any_value(), "APPROVAL_URL": Match.any_value(), "MAX_ACTIONS_PER_HOUR": "3",
        "BREAKER_FAILURES": "2", "APPROVAL_TIMEOUT_S": "1800"}}})
