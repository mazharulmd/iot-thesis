"""IoT Core stack (real AWS only): what the local bridge + Mosquitto stand in for.

  gateways --MQTT/TLS (X.509)--> IoT Core --topic rule--> DynamoDB Telemetry (DynamoDBv2 action)
                                                     └──> detector Lambda (asynchronous)
                                   errors of either action --> S3 artifacts bucket, iot-errors/
  remediation Lambda --UpdateThingShadow--> device shadow --delta--> gateway

The rule adds the same fields the bridge adds locally: `bridge_rx_ms` / `bridge_tx_ms` (the rule's
timestamp(), so the Lambda can split latency into device -> IoT Core and IoT Core -> Lambda),
`received_at` (used for telemetry freshness) and `ttl` (30 days).

The device policy lets any client whose ID starts with "dc-" connect, publish telemetry under
dc/hall1/, and use device-shadow topics. One certificate is shared by the simulated gateways and
the load generator (tools/aws_devices.py creates it); a production site would use one certificate
per gateway and the thing-name policy variables.
"""
from aws_cdk import Aws, CfnOutput, Stack
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_iot as iot
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.topology import GATEWAYS, SITE  # noqa: E402

TELEMETRY_SQL = (
    "SELECT *, timestamp() AS bridge_rx_ms, timestamp() AS bridge_tx_ms, "
    "parse_time(\"yyyy-MM-dd'T'HH:mm:ss.SSS'Z'\", timestamp()) AS received_at, "
    "floor(timestamp() / 1000) + 2592000 AS ttl "
    f"FROM '{SITE}/+/telemetry'"
)


class IotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, telemetry: ddb.ITable,
                 detector: lambda_.IFunction, errors_bucket: s3.IBucket, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        arn = f"arn:{Aws.PARTITION}:iot:{Aws.REGION}:{Aws.ACCOUNT_ID}"
        self.policy_name = f"dc-selfheal-{stage}-devices"
        iot.CfnPolicy(self, "DevicePolicy", policy_name=self.policy_name, policy_document={
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": "iot:Connect", "Resource": f"{arn}:client/dc-*"},
                {"Effect": "Allow", "Action": "iot:Publish",
                 "Resource": [f"{arn}:topic/{SITE}/*/telemetry", f"{arn}:topic/$aws/things/*/shadow/*"]},
                {"Effect": "Allow", "Action": "iot:Subscribe", "Resource": f"{arn}:topicfilter/$aws/things/*/shadow/*"},
                {"Effect": "Allow", "Action": "iot:Receive", "Resource": f"{arn}:topic/$aws/things/*/shadow/*"},
            ],
        })
        for gw in GATEWAYS:
            iot.CfnThing(self, f"Thing{gw.capitalize()}", thing_name=gw)

        role = iam.Role(self, "RuleRole", assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
                        description="IoT rule: write telemetry to DynamoDB and errors to S3")
        telemetry.grant_write_data(role)
        errors_bucket.grant_put(role)

        rule = iot.CfnTopicRule(self, "TelemetryRule", rule_name=f"dc_selfheal_{stage}_telemetry",
                                topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
            sql=TELEMETRY_SQL,
            aws_iot_sql_version="2016-03-23",
            rule_disabled=False,
            actions=[
                iot.CfnTopicRule.ActionProperty(dynamo_d_bv2=iot.CfnTopicRule.DynamoDBv2ActionProperty(
                    put_item=iot.CfnTopicRule.PutItemInputProperty(table_name=telemetry.table_name),
                    role_arn=role.role_arn)),
                iot.CfnTopicRule.ActionProperty(lambda_=iot.CfnTopicRule.LambdaActionProperty(
                    function_arn=detector.function_arn)),
            ],
            error_action=iot.CfnTopicRule.ActionProperty(s3=iot.CfnTopicRule.S3ActionProperty(
                bucket_name=errors_bucket.bucket_name, key="iot-errors/${timestamp()}-${topic(3)}.json",
                role_arn=role.role_arn)),
        ))
        # the permission lives here (not on the function's stack) so the stacks do not depend on each other
        lambda_.CfnPermission(self, "InvokeFromIotRule", action="lambda:InvokeFunction",
                              function_name=detector.function_arn, principal="iot.amazonaws.com",
                              source_arn=rule.attr_arn, source_account=Aws.ACCOUNT_ID)
        self.rule_name = rule.rule_name

        CfnOutput(self, "DevicePolicyName", value=self.policy_name)
        CfnOutput(self, "TelemetryRuleName", value=f"dc_selfheal_{stage}_telemetry")
        CfnOutput(self, "Things", value=",".join(GATEWAYS))
