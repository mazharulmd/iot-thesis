"""Remediation stack: playbook state machine, remediation Lambda, and the shadow command path.

    EventBridge (AnomalyDetected) --rule--> Step Functions (Standard) --tasks--> remediation Lambda
                                                                                  |
                    device shadow desired state  <-------------------------------+
                      real AWS: IoT Core UpdateThingShadow
                      local:    SQS queue read by the bridge (the local stand-in for IoT Core)

One state machine runs every playbook (playbooks/state_machine.py); the playbooks themselves
are data (playbooks/catalog.py) inside the Lambda. Standard workflows are used because high-risk
plans wait for human approval with a task token, which Express workflows do not support.

Guardrails (Step 6): the approval Lambda behind a function URL answers the waiting execution;
the Guardrails table holds the per-asset rate limit and circuit breaker state.
"""
import json
import sys
from pathlib import Path

from aws_cdk import Aws, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from playbooks.state_machine import definition  # noqa: E402

BUILD_DIR = ROOT / "build" / "remediation"
APPROVAL_BUILD_DIR = ROOT / "build" / "approval"


class RemediationStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, telemetry: ddb.ITable,
                 incidents: ddb.ITable, locks: ddb.ITable, guardrails: ddb.ITable, bus: events.IEventBus,
                 alerts: sns.ITopic, shadow_transport: str = "sqs", automation: str = "on", poll_s: int = 10,
                 approval_timeout_s: int = 1800, max_actions_per_hour: int = 3, breaker_failures: int = 2,
                 iot_data_endpoint: str = "", code_dir: Path = BUILD_DIR,
                 approval_code_dir: Path = APPROVAL_BUILD_DIR, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        for d in (code_dir, approval_code_dir):
            if not Path(d).exists():
                raise FileNotFoundError(f"{d} not found: run `make build-lambdas` first")
        if shadow_transport not in ("sqs", "iot"):
            raise ValueError("shadow_transport must be 'sqs' or 'iot'")

        # Approval: a function URL (no AWS credentials needed in the browser); the one-time nonce
        # in the link is the secret, and GET only shows the plan (the buttons POST the decision).
        self.approval = lambda_.Function(
            self, "Approval",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(approval_code_dir)),
            memory_size=128,
            timeout=Duration.seconds(10),
            log_group=logs.LogGroup(self, "ApprovalLogs", retention=logs.RetentionDays.ONE_WEEK,
                                    removal_policy=RemovalPolicy.DESTROY),
            environment={"INCIDENTS_TABLE": incidents.table_name},
            description=f"dc-selfheal {stage}: approve or reject high-risk remediation",
        )
        incidents.grant_read_write_data(self.approval)
        approval_url = self.approval.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        env = {
            "INCIDENTS_TABLE": incidents.table_name,
            "GUARDRAILS_TABLE": guardrails.table_name,
            "APPROVAL_URL": approval_url.url,
            "APPROVAL_TIMEOUT_S": str(approval_timeout_s),
            "MAX_ACTIONS_PER_HOUR": str(max_actions_per_hour),
            "BREAKER_FAILURES": str(breaker_failures),
            "LOCKS_TABLE": locks.table_name,
            "TELEMETRY_TABLE": telemetry.table_name,
            "ALERTS_TOPIC": alerts.topic_arn,
            "SHADOW_TRANSPORT": shadow_transport,
            "AUTOMATION": automation,
            "POLL_S": str(poll_s),
        }
        queue = None
        if shadow_transport == "sqs":
            queue = sqs.Queue(self, "ShadowUpdates", retention_period=Duration.hours(1),
                              removal_policy=RemovalPolicy.DESTROY)
            env["SHADOW_QUEUE_URL"] = queue.queue_url
        elif iot_data_endpoint:
            env["IOT_DATA_ENDPOINT"] = iot_data_endpoint

        log_group = logs.LogGroup(self, "RemediationLogs", retention=logs.RetentionDays.ONE_WEEK,
                                  removal_policy=RemovalPolicy.DESTROY)
        self.function = lambda_.Function(
            self, "Remediation",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(code_dir)),
            memory_size=256,
            timeout=Duration.seconds(30),
            log_group=log_group,
            environment=env,
            description=f"dc-selfheal {stage}: remediation playbook steps",
        )
        telemetry.grant_read_data(self.function)
        incidents.grant_read_write_data(self.function)
        locks.grant_read_write_data(self.function)
        guardrails.grant_read_write_data(self.function)
        alerts.grant_publish(self.function)
        if queue is not None:
            queue.grant_send_messages(self.function)
        else:
            self.function.add_to_role_policy(iam.PolicyStatement(
                actions=["iot:UpdateThingShadow", "iot:GetThingShadow"],
                resources=[f"arn:{Aws.PARTITION}:iot:{Aws.REGION}:{Aws.ACCOUNT_ID}:thing/*"]))
            self.function.add_to_role_policy(iam.PolicyStatement(    # finds the account's data endpoint
                actions=["iot:DescribeEndpoint"], resources=["*"]))

        self.state_machine = sfn.StateMachine(
            self, "Playbooks",
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_string(
                json.dumps(definition(self.function.function_arn, approval_timeout_s))),
            timeout=Duration.hours(3),
            comment="dc-selfheal remediation playbooks",
        )
        self.function.grant_invoke(self.state_machine)
        # A separate policy (not the function's default one) avoids a dependency cycle:
        # approval function -> its URL -> remediation env -> state machine -> this permission.
        iam.Policy(self, "ApprovalTaskResponse", roles=[self.approval.role], statements=[iam.PolicyStatement(
            actions=["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"],
            resources=[self.state_machine.state_machine_arn])])

        playbook_rule = events.Rule(self, "AnomalyToPlaybooks", event_bus=bus,
                    event_pattern=events.EventPattern(source=["dc.selfheal.detector"],
                                                      detail_type=["AnomalyDetected"]),
                    targets=[targets.SfnStateMachine(self.state_machine,
                                                     input=events.RuleTargetInput.from_event_path("$.detail"))])

        CfnOutput(self, "RemediationFunctionName", value=self.function.function_name)
        CfnOutput(self, "PlaybookRuleName", value=playbook_rule.rule_name)
        CfnOutput(self, "StateMachineArn", value=self.state_machine.state_machine_arn)
        CfnOutput(self, "ApprovalFunctionName", value=self.approval.function_name)
        CfnOutput(self, "ApprovalUrl", value=approval_url.url)
        if queue is not None:
            CfnOutput(self, "ShadowQueueUrl", value=queue.queue_url)
