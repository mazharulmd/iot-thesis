"""Detection stack: detector Lambda, anomaly event bus, and a queue for anomaly events.

The detector replaces Step 3's ingest probe behind the same invocation path and keeps
updating the IngestStats table (heartbeat and latency). New anomalies go to a custom
EventBridge bus. The remediation stack's rule starts the playbooks from that bus; a second
rule here copies every AnomalyDetected event to an SQS queue so it can be inspected.
"""
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs
from constructs import Construct

BUILD_DIR = Path(__file__).resolve().parents[2] / "build" / "detector"


class DetectionStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, telemetry: ddb.ITable,
                 ingest_stats: ddb.ITable, detections: ddb.ITable, detector: str = "d2h",
                 code_dir: Path = BUILD_DIR, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        if not Path(code_dir).exists():
            raise FileNotFoundError(f"{code_dir} not found: run `make build-lambdas` first")

        self.bus = events.EventBus(self, "AnomalyBus", event_bus_name=f"dc-selfheal-{stage}")

        log_group = logs.LogGroup(self, "DetectorLogs", retention=logs.RetentionDays.ONE_WEEK,
                                  removal_policy=RemovalPolicy.DESTROY)
        self.function = lambda_.Function(
            self, "Detector",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(code_dir)),
            memory_size=512,
            timeout=Duration.seconds(15),
            log_group=log_group,
            environment={
                "DETECTOR": detector,
                "TELEMETRY_TABLE": telemetry.table_name,
                "STATS_TABLE": ingest_stats.table_name,
                "DETECTIONS_TABLE": detections.table_name,
                "EVENT_BUS": self.bus.event_bus_name,
            },
            description=f"dc-selfheal {stage}: anomaly detection ({detector}) per gateway message",
        )
        telemetry.grant_read_data(self.function)
        ingest_stats.grant_read_write_data(self.function)
        detections.grant_write_data(self.function)
        self.bus.grant_put_events_to(self.function)

        # Every anomaly event also goes to a queue for inspection and tests (make events)
        self.queue = sqs.Queue(self, "AnomalyEvents", retention_period=Duration.days(4),
                               removal_policy=RemovalPolicy.DESTROY)
        events.Rule(self, "AnomalyToQueue", event_bus=self.bus,
                    event_pattern=events.EventPattern(source=["dc.selfheal.detector"],
                                                      detail_type=["AnomalyDetected"]),
                    targets=[targets.SqsQueue(self.queue)])

        CfnOutput(self, "DetectorFunctionName", value=self.function.function_name)
        CfnOutput(self, "EventBusName", value=self.bus.event_bus_name)
        CfnOutput(self, "AnomalyQueueUrl", value=self.queue.queue_url)
