"""Device certificate for the gateways and the load generator on AWS IoT Core.

    python -m tools.aws_devices create [--stage dev]    (make aws-devices)
    python -m tools.aws_devices show
    python -m tools.aws_devices delete [--stage dev]    (part of make aws-destroy)

`create` makes an X.509 certificate with IoT Core, attaches the stack's device policy, and writes
into certs/ (git-ignored, private key readable only by you):

    device.pem.crt  private.pem.key  AmazonRootCA1.pem  endpoint.txt  certificate.json

The simulator and load generator connect with `--aws-certs certs`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from common.awsenv import session, stack_outputs

CERTS = Path(__file__).resolve().parents[1] / "certs"
ROOT_CA_URL = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"


def endpoint(sess) -> str:
    return sess.client("iot").describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]


def create(sess, policy: str, folder: Path = CERTS, fetch_ca=None) -> dict:
    meta_file = folder / "certificate.json"
    if meta_file.exists():
        sys.exit(f"{meta_file} exists: a certificate was already created (delete it first)")
    iot = sess.client("iot")
    resp = iot.create_keys_and_certificate(setAsActive=True)
    iot.attach_policy(policyName=policy, target=resp["certificateArn"])
    folder.mkdir(exist_ok=True)
    (folder / "device.pem.crt").write_text(resp["certificatePem"])
    key = folder / "private.pem.key"
    key.write_text(resp["keyPair"]["PrivateKey"])
    os.chmod(key, 0o600)
    (folder / "AmazonRootCA1.pem").write_text((fetch_ca or _fetch_ca)())
    host = endpoint(sess)
    (folder / "endpoint.txt").write_text(host + "\n")
    meta = {"certificateId": resp["certificateId"], "certificateArn": resp["certificateArn"],
            "policy": policy, "endpoint": host}
    meta_file.write_text(json.dumps(meta, indent=2))
    return meta


def delete(sess, folder: Path = CERTS) -> str | None:
    meta_file = folder / "certificate.json"
    if not meta_file.exists():
        return None
    meta = json.loads(meta_file.read_text())
    iot = sess.client("iot")
    try:
        iot.detach_policy(policyName=meta["policy"], target=meta["certificateArn"])
    except iot.exceptions.ResourceNotFoundException:
        pass
    iot.update_certificate(certificateId=meta["certificateId"], newStatus="INACTIVE")
    iot.delete_certificate(certificateId=meta["certificateId"], forceDelete=True)
    for name in ("device.pem.crt", "private.pem.key", "AmazonRootCA1.pem", "endpoint.txt", "certificate.json"):
        (folder / name).unlink(missing_ok=True)
    return meta["certificateId"]


def _fetch_ca() -> str:
    with urllib.request.urlopen(ROOT_CA_URL, timeout=20) as resp:
        return resp.read().decode()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["create", "show", "delete"])
    ap.add_argument("--stage", default="dev")
    args = ap.parse_args()
    if args.stage == "local":
        sys.exit("IoT Core certificates are for real AWS; locally the gateways use Mosquitto")
    sess = session(args.stage)
    if args.action == "create":
        out = stack_outputs(sess, args.stage)
        if "DevicePolicyName" not in out:
            sys.exit("IoT stack not found: run make aws-deploy first")
        meta = create(sess, out["DevicePolicyName"])
        print(f"certificate {meta['certificateId'][:12]}… attached to {meta['policy']}; endpoint {meta['endpoint']}")
        print(f"files in {CERTS}/ (keep private.pem.key secret)")
    elif args.action == "show":
        meta_file = CERTS / "certificate.json"
        print(meta_file.read_text() if meta_file.exists() else "no certificate created")
    else:
        cid = delete(sess)
        print(f"certificate {cid[:12]}… deleted" if cid else "no certificate to delete")


if __name__ == "__main__":
    main()
