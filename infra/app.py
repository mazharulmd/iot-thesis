#!/usr/bin/env python3
"""CDK entry point for the dc-selfheal thesis project.

Usage:
    cdk deploy --all -c stage=dev -c alert_email=you@example.com [-c ddb_billing=on_demand]   (real AWS)
    cdklocal deploy --all -c stage=local                                                      (LocalStack)

On real AWS an IoT Core stack (device policy, things, telemetry rule) replaces the local bridge.
"""
import os

import aws_cdk as cdk

from stacks.data_stack import DataStack
from stacks.foundation_stack import FoundationStack
from stacks.detection_stack import DetectionStack
from stacks.iot_stack import IotStack
from stacks.remediation_stack import RemediationStack

app = cdk.App()

stage = app.node.try_get_context("stage") or "dev"
alert_email = app.node.try_get_context("alert_email")

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION"),
)

foundation = FoundationStack(
    app,
    f"DcSelfheal-{stage}-Foundation",
    stage=stage,
    alert_email=alert_email,
    env=env,
    description="dc-selfheal: shared bucket and alert topic (Step 1)",
)

data = DataStack(
    app,
    f"DcSelfheal-{stage}-Data",
    stage=stage,
    on_demand=(app.node.try_get_context("ddb_billing") == "on_demand"),
    env=env,
    description="dc-selfheal: DynamoDB tables (Step 3)",
)

detection = DetectionStack(
    app,
    f"DcSelfheal-{stage}-Detection",
    stage=stage,
    telemetry=data.telemetry,
    ingest_stats=data.ingest_stats,
    detections=data.detections,
    detector=app.node.try_get_context("detector") or "d2h",
    env=env,
    description="dc-selfheal: detector Lambda and anomaly event bus (Step 4)",
)

RemediationStack(
    app,
    f"DcSelfheal-{stage}-Remediation",
    stage=stage,
    telemetry=data.telemetry,
    incidents=data.incidents,
    locks=data.locks,
    guardrails=data.guardrails,
    bus=detection.bus,
    alerts=foundation.alerts_topic,
    # locally the bridge stands in for IoT Core and reads shadow updates from a queue
    shadow_transport=app.node.try_get_context("shadow_transport") or ("sqs" if stage == "local" else "iot"),
    automation=app.node.try_get_context("automation") or "on",
    poll_s=int(app.node.try_get_context("poll_s") or 10),
    approval_timeout_s=int(app.node.try_get_context("approval_timeout_s") or 1800),
    max_actions_per_hour=int(app.node.try_get_context("max_actions_per_hour") or 3),
    breaker_failures=int(app.node.try_get_context("breaker_failures") or 2),
    iot_data_endpoint=app.node.try_get_context("iot_data_endpoint") or "",
    env=env,
    description="dc-selfheal: remediation playbooks, approvals and guardrails (Steps 5-6)",
)

if stage != "local":                # LocalStack's free plan has no IoT Core: the bridge replaces it
    IotStack(
        app,
        f"DcSelfheal-{stage}-Iot",
        stage=stage,
        telemetry=data.telemetry,
        detector=detection.function,
        errors_bucket=foundation.artifacts_bucket,
        env=env,
        description="dc-selfheal: IoT Core device policy, things and telemetry rule (Step 8)",
    )

# Tags on every resource, used by Cost Explorer for per-experiment cost (E3).
cdk.Tags.of(app).add("Project", "dc-selfheal")
cdk.Tags.of(app).add("Stage", stage)

app.synth()
