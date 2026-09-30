"""Approve or reject a high-risk plan that is waiting for a human.

    python -m tools.approve --pending                       list waiting approvals (make approvals)
    python -m tools.approve --id <incident> [--by NAME]     approve (make approve I=<id>)
    python -m tools.approve --id <incident> --reject        reject  (make reject I=<id>)
    python -m tools.approve --id <incident> --via-url       use the function URL like the email link

The decision goes through the approval Lambda either way, with the same one-time nonce checks.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.parse
import urllib.request

from common.awsenv import session, stack_outputs

from .incidents import plain, scan_all, tables


def approval_item(incidents, incident_id: str) -> dict | None:
    item = incidents.get_item(Key={"id": incident_id, "sk": "APPROVAL"}).get("Item")
    return plain(item) if item else None


def link(out: dict, incident_id: str, nonce: str) -> str:
    return f"{out['ApprovalUrl'].rstrip('/')}/?incident={incident_id}&nonce={nonce}"


def decide(sess, out: dict, incident_id: str, nonce: str, decision: str, by: str, via_url: bool = False) -> dict:
    if via_url:
        data = urllib.parse.urlencode({"incident": incident_id, "nonce": nonce, "decision": decision, "by": by})
        req = urllib.request.Request(out["ApprovalUrl"], data=data.encode(), method="POST",
                                     headers={"content-type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return {"status": resp.status, "message": resp.read().decode()[:400]}
        except urllib.error.HTTPError as exc:
            return {"status": exc.code, "message": exc.read().decode()[:400]}
    resp = sess.client("lambda").invoke(FunctionName=out["ApprovalFunctionName"], Payload=json.dumps(
        {"incident": incident_id, "nonce": nonce, "decision": decision, "by": by}).encode())
    return json.loads(resp["Payload"].read())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", default="local")
    ap.add_argument("--id")
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--by", default=getpass.getuser())
    ap.add_argument("--via-url", action="store_true")
    ap.add_argument("--pending", action="store_true")
    args = ap.parse_args()
    sess = session(args.stage)
    out = stack_outputs(sess, args.stage)
    incidents, _ = tables(args.stage)

    if args.pending or not args.id:
        waiting = [plain(i) for i in scan_all(incidents) if i["sk"] == "APPROVAL" and i["status"] == "pending"]
        if not waiting:
            print("no approvals waiting")
        for item in waiting:
            summary = plain(incidents.get_item(Key={"id": item["id"], "sk": "A"})["Item"])
            print(f"{item['id']}  {summary['fault_type']} on {summary['target']}  "
                  f"requested {item['requested_at']}\n  {link(out, item['id'], item['nonce'])}")
        return
    item = approval_item(incidents, args.id)
    if not item:
        sys.exit(f"incident {args.id} has no approval request")
    res = decide(sess, out, args.id, item["nonce"], "reject" if args.reject else "approve", args.by, args.via_url)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("status") == 200 else 1)


if __name__ == "__main__":
    main()
