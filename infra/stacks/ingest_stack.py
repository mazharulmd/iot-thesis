"""Ingest stack: the Lambda that receives every gateway message.

In Step 3 this is a probe that records counts and latency. In Step 4 the
detector replaces it behind the same invocation path.
"""
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

LAMBDA_DIR = Path(__file__).resolve().parents[2] / "lambdas"


class IngestStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str,
                 ingest_stats: ddb.ITable, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_group = logs.LogGroup(
            self, "IngestProbeLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.function = lambda_.Function(
            self, "IngestProbe",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(LAMBDA_DIR / "ingest_probe")),
            memory_size=128,
            timeout=Duration.seconds(10),
            environment={"STATS_TABLE": ingest_stats.table_name},
            log_group=log_group,
            description=f"dc-selfheal {stage}: per-gateway message counts and latency",
        )
        ingest_stats.grant_read_write_data(self.function)

        CfnOutput(self, "IngestFunctionName", value=self.function.function_name)
