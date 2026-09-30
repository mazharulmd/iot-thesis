import pathlib
import sys

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "infra"))

from stacks.foundation_stack import FoundationStack  # noqa: E402


def _template(alert_email="alerts@example.com"):
    app = cdk.App()
    stack = FoundationStack(app, "Test", stage="test", alert_email=alert_email)
    return Template.from_stack(stack)


def test_bucket_is_private_and_encrypted():
    t = _template()
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "BucketEncryption": {
                "ServerSideEncryptionConfiguration": [
                    {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            },
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        },
    )


def test_bucket_requires_tls():
    t = _template()
    t.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Effect": "Deny",
                                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                            }
                        )
                    ]
                )
            }
        },
    )


def test_email_subscription_added_only_when_given():
    _template().resource_count_is("AWS::SNS::Subscription", 1)
    _template(alert_email=None).resource_count_is("AWS::SNS::Subscription", 0)
