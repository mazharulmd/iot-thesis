"""Data stack: DynamoDB tables.

Provisioned capacity is kept small so all tables together stay inside
DynamoDB's always-free 25 WCU / 25 RCU on real AWS. With on_demand=True (CDK context
ddb_billing=on_demand) every table is pay-per-request instead: needed for runs at x10 speed
and for load tests, which exceed the free provisioned capacity.
"""
from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as ddb
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, on_demand: bool = False,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        def capacity(read: int, write: int) -> dict:
            if on_demand:
                return {"billing_mode": ddb.BillingMode.PAY_PER_REQUEST}
            return {"billing_mode": ddb.BillingMode.PROVISIONED, "read_capacity": read, "write_capacity": write}

        # One item per gateway message: pk = gateway, sk = message timestamp
        self.telemetry = ddb.Table(
            self, "Telemetry",
            partition_key=ddb.Attribute(name="gw", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="ts", type=ddb.AttributeType.STRING),
            **capacity(5, 5),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # One item per gateway: message count, last seen, pipeline latency
        self.ingest_stats = ddb.Table(
            self, "IngestStats",
            partition_key=ddb.Attribute(name="gw", type=ddb.AttributeType.STRING),
            **capacity(2, 2),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # One item per detected anomaly: pk = day, sk = "<ts>#<target>#<fault>"
        self.detections = ddb.Table(
            self, "Detections",
            partition_key=ddb.Attribute(name="day", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="id", type=ddb.AttributeType.STRING),
            **capacity(1, 1),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Remediation audit trail: pk = incident id, sk = "A" (summary) or "L#<time>#<n>" (one per step)
        self.incidents = ddb.Table(
            self, "Incidents",
            partition_key=ddb.Attribute(name="id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            **capacity(2, 2),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Asset locks: pk = asset; a conditional write takes the lock (expires_at, TTL cleans up)
        self.locks = ddb.Table(
            self, "Locks",
            partition_key=ddb.Attribute(name="asset", type=ddb.AttributeType.STRING),
            **capacity(2, 2),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Guardrail state: pk = "rate#<asset>" (recent automated actions) or "breaker#<asset>" (failures)
        self.guardrails = ddb.Table(
            self, "Guardrails",
            partition_key=ddb.Attribute(name="key", type=ddb.AttributeType.STRING),
            **capacity(1, 1),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        CfnOutput(self, "TelemetryTableName", value=self.telemetry.table_name)
        CfnOutput(self, "GuardrailsTableName", value=self.guardrails.table_name)
        CfnOutput(self, "IncidentsTableName", value=self.incidents.table_name)
        CfnOutput(self, "LocksTableName", value=self.locks.table_name)
        CfnOutput(self, "IngestStatsTableName", value=self.ingest_stats.table_name)
        CfnOutput(self, "DetectionsTableName", value=self.detections.table_name)
