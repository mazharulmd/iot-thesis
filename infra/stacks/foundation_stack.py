"""Foundation stack: resources shared by all later stacks.

- S3 artifacts bucket: trained models, data exports, IoT rule error archive.
- SNS alerts topic: approval requests and operational alerts.
"""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct


class FoundationStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        alert_email: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.artifacts_bucket = s3.Bucket(
            self,
            "ArtifactsBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            # Thesis project: allow `cdk destroy` to remove everything.
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-iot-errors",
                    prefix="iot-errors/",
                    expiration=Duration.days(30),
                )
            ],
        )

        self.alerts_topic = sns.Topic(
            self,
            "AlertsTopic",
            display_name=f"dc-selfheal {stage} alerts",
        )
        if alert_email:
            self.alerts_topic.add_subscription(subs.EmailSubscription(alert_email))

        CfnOutput(self, "ArtifactsBucketName", value=self.artifacts_bucket.bucket_name)
        CfnOutput(self, "AlertsTopicArn", value=self.alerts_topic.topic_arn)
