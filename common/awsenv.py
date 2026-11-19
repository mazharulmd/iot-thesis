"""AWS session and stack outputs for local (LocalStack) or real AWS use."""
from __future__ import annotations

import os

import boto3

STACKS = ("Foundation", "Data", "Detection", "Remediation", "Iot", "Monitoring")


def session(stage: str) -> boto3.Session:
    """For stage 'local', point every client at LocalStack unless told otherwise."""
    if stage == "local":
        os.environ.setdefault("AWS_ENDPOINT_URL", "http://localhost:4566")
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "eu-north-1"))
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


def iot_data_endpoint(sess: boto3.Session, wait_s: float = 900.0) -> str:
    """The account's IoT Core data endpoint (ATS), once its DNS name resolves.

    The first describe_endpoint call in a new account or region creates the endpoint, and its DNS
    name can take several minutes (sometimes up to about 15) to become resolvable; until then every
    call fails with 'Name or service not known'. Wait for it instead of failing.
    """
    import socket
    import time

    host = sess.client("iot").describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
    if os.environ.get("AWS_ENDPOINT_URL"):           # LocalStack: no DNS to wait for
        return host
    deadline, said = time.time() + wait_s, False
    while True:
        try:
            socket.getaddrinfo(host, 443)
            if said:
                print(f"{host} resolves now.", flush=True)
            return host
        except socket.gaierror:
            if time.time() > deadline:
                raise RuntimeError(f"IoT endpoint {host} still does not resolve after {wait_s:.0f} s; "
                                   "try again later")
            if not said:
                print(f"Waiting for the new IoT Core endpoint {host} to appear in DNS "
                      "(first use in this region; can take up to ~15 min) ...", flush=True)
                said = True
            time.sleep(15)
