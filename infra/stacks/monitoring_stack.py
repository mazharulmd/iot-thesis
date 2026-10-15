"""Monitoring stack: one CloudWatch dashboard for the whole pipeline (real AWS only).

Rows follow the path of a message: IoT Core in -> detector Lambda -> DynamoDB -> playbooks
(Step Functions) -> remediation Lambdas and alerts. All metrics are AWS service metrics, so
nothing is added to the detector's hot path. One dashboard with fewer than 50 metrics is inside
CloudWatch's always-free allowance (3 dashboards).

End-to-end latency (sensor -> detector) is not a CloudWatch metric: it is kept as a histogram in
the IngestStats table and read by `make status`, `make aws-check` and the load test.
"""
from __future__ import annotations

from aws_cdk import Aws, CfnOutput, Duration, Stack
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

PERIOD = Duration.minutes(1)


def _m(namespace: str, name: str, dims: dict, stat: str = "Sum", label: str | None = None) -> cw.Metric:
    return cw.Metric(namespace=namespace, metric_name=name, dimensions_map=dims, statistic=stat,
                     period=PERIOD, label=label or name)


class MonitoringStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, detector: lambda_.IFunction,
                 remediation: lambda_.IFunction, approval: lambda_.IFunction, state_machine: sfn.IStateMachine,
                 telemetry: ddb.ITable, ingest_stats: ddb.ITable, alerts: sns.ITopic, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        rule = f"dc_selfheal_{stage}_telemetry"          # fixed name set in the IoT stack
        self.dashboard_name = f"dc-selfheal-{stage}"
        dash = cw.Dashboard(self, "Dashboard", dashboard_name=self.dashboard_name,
                            default_interval=Duration.hours(3))

        def graph(title: str, metrics: list, width: int = 8, unit: str = "") -> cw.GraphWidget:
            return cw.GraphWidget(title=title, left=metrics, width=width, height=6,
                                  left_y_axis=cw.YAxisProps(min=0, label=unit, show_units=False),
                                  legend_position=cw.LegendPosition.BOTTOM)

        dash.add_widgets(cw.TextWidget(width=24, height=2, markdown=(
            f"### dc-selfheal ({stage}): telemetry → detection → remediation\n"
            "Per-minute sums unless noted. Sensor-to-detector latency is in the IngestStats table "
            "(`make status`, load-test summary), not here.")))

        # Row 1: ingestion
        dash.add_widgets(
            graph("IoT Core: messages in and rule matches", [
                _m("AWS/IoT", "PublishIn.Success", {"Protocol": "MQTT"}, label="messages published"),
                _m("AWS/IoT", "TopicMatch", {"RuleName": rule}, label="telemetry rule matches"),
            ], unit="count / min"),
            graph("IoT Core: rule problems", [
                _m("AWS/IoT", "Failure", {"RuleName": rule, "ActionType": "DynamoDBv2"}, label="DynamoDB action failed"),
                _m("AWS/IoT", "Failure", {"RuleName": rule, "ActionType": "Lambda"}, label="Lambda action failed"),
                _m("AWS/IoT", "ParseError", {"RuleName": rule}, label="parse errors"),
                _m("AWS/IoT", "RuleMessageThrottled", {"RuleName": rule}, label="throttled"),
            ], unit="count / min"),
            graph("Detector Lambda: invocations, errors, throttles", [
                detector.metric_invocations(period=PERIOD, label="invocations"),
                detector.metric_errors(period=PERIOD, label="errors"),
                detector.metric_throttles(period=PERIOD, label="throttles"),
            ], unit="count / min"),
        )
        # Row 2: detector performance and storage
        dash.add_widgets(
            graph("Detector Lambda: duration", [
                detector.metric_duration(period=PERIOD, statistic="Average", label="average"),
                detector.metric_duration(period=PERIOD, statistic="p95", label="p95"),
            ], unit="ms"),
            graph("Detector Lambda: concurrent executions (max)", [
                _m("AWS/Lambda", "ConcurrentExecutions", {"FunctionName": detector.function_name}, "Maximum",
                   label="concurrent executions"),
            ], unit="executions"),
            graph("DynamoDB: write capacity used", [
                telemetry.metric_consumed_write_capacity_units(period=PERIOD, label="Telemetry"),
                ingest_stats.metric_consumed_write_capacity_units(period=PERIOD, label="IngestStats"),
            ], unit="WCU / min"),
        )
        # Row 3: remediation
        arn = {"StateMachineArn": state_machine.state_machine_arn}
        dash.add_widgets(
            graph("Playbooks (Step Functions executions)", [
                _m("AWS/States", "ExecutionsStarted", arn, label="started"),
                _m("AWS/States", "ExecutionsSucceeded", arn, label="succeeded"),
                _m("AWS/States", "ExecutionsFailed", arn, label="failed"),
                _m("AWS/States", "ExecutionsTimedOut", arn, label="timed out"),
            ], unit="count / min"),
            graph("Remediation and approval Lambdas: errors", [
                remediation.metric_errors(period=PERIOD, label="remediation errors"),
                approval.metric_errors(period=PERIOD, label="approval errors"),
                _m("AWS/DynamoDB", "WriteThrottleEvents", {"TableName": telemetry.table_name},
                   label="Telemetry write throttles"),
            ], unit="count / min"),
            graph("Alerts and approval requests sent (SNS)", [
                alerts.metric_number_of_messages_published(period=PERIOD, label="messages published"),
            ], unit="count / min"),
        )

        region = Aws.REGION
        self.url = (f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}"
                    f"#dashboards/dashboard/{self.dashboard_name}")
        CfnOutput(self, "DashboardName", value=self.dashboard_name)
        CfnOutput(self, "DashboardUrl", value=self.url)
