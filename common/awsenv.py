"""AWS session and stack outputs for local (LocalStack) or real AWS use."""
from __future__ import annotations

import os

import boto3

STACKS = ("Foundation", "Data", "Detection", "Remediation", "Iot")


def session(stage: str) -> boto3.Session:
    """For stage 'local', point every client at LocalStack unless told otherwise."""
    if stage == "local":
        os.environ.setdefault("AWS_ENDPOINT_URL", "http://localhost:4566")
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "ap-south-1"))
    return boto3.Session()


def stack_outputs(sess: boto3.Session, stage: str, stacks=STACKS) -> dict:
    """Outputs of every deployed stack; stacks that are not deployed are skipped
    (callers check for the outputs they need). Fails if none is deployed."""
    from botocore.exceptions import ClientError

    cfn = sess.client("cloudformation")
    out, found = {}, 0
    for name in stacks:
        try:
            stack = cfn.describe_stacks(StackName=f"DcSelfheal-{stage}-{name}")["Stacks"][0]
        except ClientError as exc:
            if "does not exist" in str(exc):
                continue
            raise
        found += 1
        out.update({o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])})
    if not found:
        raise RuntimeError(f"no DcSelfheal-{stage}-* stacks deployed")
    return out
