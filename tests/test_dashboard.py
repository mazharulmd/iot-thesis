"""Live dashboard: state snapshot, simulation source, AWS source (mocked) and the HTTP server."""
import json
import threading
import time
import urllib.error
import urllib.request

import boto3
import pytest
from moto import mock_aws

from dashboard.core import LiveState, alerts_from, incident_view, series_point
from dashboard.server import serve


def _msg(gw, seq, t_in=21.0):
    assets = {"rack01": {"t_in": t_in, "t_out": 35.0, "p_kw": 40.0}, "crah1": {"status": "on", "fan_pct": 60}}
    return {"gw": gw, "ts": f"2026-12-01T10:00:{seq:02d}.000Z", "seq": seq, "assets": assets}


def test_snapshot_kpis_and_series():
    st = LiveState("simulation")
    st.message(_msg("zone1", 1, 29.5), 10.0)
    st.message(_msg("zone1", 1, 29.5), 10.0)                  # same sequence number: ignored
    snap = st.snapshot()
    assert snap["kpis"]["messages"] == 1
    assert snap["kpis"]["hottest_inlet_c"] == 29.5 and snap["kpis"]["racks_over_limit"] == 1
    assert series_point(st.gateways)["zone1_inlet"] == 29.5
    json.dumps(snap)                                          # serialisable


def test_incident_view_steps_and_alerts():
    s = {"id": "i1", "sk": "A", "status": "mitigated", "fault_type": "crah_fan_failure", "target": "crah2",
         "risk": "low", "opened_at": "2026-12-01T10:00:00.000Z", "closed_at": "2026-12-01T10:03:00.000Z"}
    log = [{"step": "opened", "at": "2026-12-01T10:00:00.000Z"}, {"step": "act", "at": "2026-12-01T10:00:01.000Z"},
           {"step": "verified", "at": "2026-12-01T10:02:30.000Z"}, {"step": "closed", "at": "2026-12-01T10:03:00.000Z"}]
    from datetime import datetime
    v = incident_view(s, log, lambda ts: datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    assert list(v["steps"]) == ["opened", "act", "verified", "closed"] and v["recovery_s"] == 180.0
    assert alerts_from([v])[0]["subject"].startswith("Mitigated")


def test_simulation_detects_and_fixes_an_injected_fault():
    from dashboard.sim import SimulationSource
    st = LiveState("simulation")
    src = SimulationSource(st, speed=120.0 * 5, hours=2.0)
    src.start()
    try:
        deadline = time.time() + 120
        while not st.gateways and time.time() < deadline:
            time.sleep(0.2)
        assert "injected" in src.inject("crah_fan_failure")
        while time.time() < deadline:
            incs = st.snapshot()["incidents"]
            if any(i["fault_type"] == "crah_fan_failure" and i["status"] == "mitigated" for i in incs):
                break
            time.sleep(0.2)
        snap = st.snapshot()
        assert any(i["fault_type"] == "crah_fan_failure" and i["status"] == "mitigated" for i in snap["incidents"])
        assert snap["faults"][0]["type"] == "crah_fan_failure" and snap["kpis"]["commands"] > 0
        assert not snap["error"]
    finally:
        src.stop()


class _Stub:
    speed = 1.0

    def __init__(self):
        self.calls = []

    def inject(self, f):
        self.calls.append(("inject", f))
        return "ok"

    def decide(self, inc, d):
        if d not in ("approve", "reject"):
            raise ValueError("bad decision")
        return "ok"


def _start(token):
    st, stub = LiveState("simulation"), _Stub()
    httpd = serve(st, stub, "127.0.0.1", 0, token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, stub, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as r:
        return r.status, r.read()


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_server_requires_the_token_when_set():
    httpd, stub, base = _start("s3cret")
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + "/api/state")
        assert exc.value.code == 403
        assert _get(base + "/?token=s3cret")[0] == 200
        assert _get(base + "/api/state", {"X-Token": "s3cret"})[0] == 200
        assert _post(base + "/api/inject", {"fault": "x"})[0] == 403
        assert _post(base + "/api/inject", {"fault": "pdu_overload"}, {"X-Token": "s3cret"}) == (200, {"ok": True, "message": "ok"})
        assert stub.calls == [("inject", "pdu_overload")]
        assert _post(base + "/api/decide", {"incident": "i", "decision": "maybe"}, {"X-Token": "s3cret"})[0] == 400
    finally:
        httpd.shutdown()


def test_server_without_token_on_localhost():
    httpd, _, base = _start(None)
    try:
        status, body = _get(base + "/api/state")
        assert status == 200 and json.loads(body)["mode"] == "simulation"
    finally:
        httpd.shutdown()


@mock_aws
def test_aws_source_reads_the_deployed_tables(monkeypatch):
    import dashboard.aws as aws
    ddb = boto3.resource("dynamodb", region_name="eu-north-1")

    def table(name, hk, rk=None):
        ks = [{"AttributeName": hk, "KeyType": "HASH"}] + ([{"AttributeName": rk, "KeyType": "RANGE"}] if rk else [])
        ad = [{"AttributeName": a, "AttributeType": "S"} for a in [hk] + ([rk] if rk else [])]
        return ddb.create_table(TableName=name, KeySchema=ks, AttributeDefinitions=ad, BillingMode="PAY_PER_REQUEST")

    tel, inc, det, stats = table("T", "gw", "ts"), table("I", "id", "sk"), table("D", "day", "id"), table("S", "gw")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    tel.put_item(Item=json.loads(json.dumps({**_msg("zone1", 5), "ts": now}), parse_float=__import__("decimal").Decimal))
    det.put_item(Item={"day": now[:10], "id": f"{now}#crah2#crah_fan_failure", "ts": now, "fault_type": "crah_fan_failure",
                       "target": "crah2", "asset": "crah2", "gw": "zone2"})
    inc.put_item(Item={"id": "i1", "sk": "A", "status": "awaiting_approval", "fault_type": "ups_battery_overheat",
                       "target": "ups1", "risk": "high", "playbook": "ups_load_transfer", "opened_at": now,
                       "plan": {"stages": [{"name": "transfer", "commands": {"ups1": {"load_share": 0}}}]}})
    inc.put_item(Item={"id": "i1", "sk": "L#" + now + "#00001", "step": "opened", "at": now})
    stats.put_item(Item={"gw": "zone1", "last_latency_ms": 120})
    stats.put_item(Item={"gw": "lg-2000-00001", "last_latency_ms": 9999})     # load-test gateway: ignored
    det.put_item(Item={"day": now[:10], "id": f"{now}#lg#unexplained", "ts": now, "fault_type": "unexplained",
                       "target": "rack01", "asset": "rack01", "gw": "lg-2000-00001"})

    monkeypatch.setattr(aws, "session", lambda stage: boto3.Session(region_name="eu-north-1"))
    monkeypatch.setattr(aws, "stack_outputs", lambda sess, stage: {
        "TelemetryTableName": "T", "IncidentsTableName": "I", "DetectionsTableName": "D", "IngestStatsTableName": "S"})
    st = LiveState("aws")
    src = aws.AwsSource(st, "dev")
    src.poll()
    snap = st.snapshot()
    assert snap["gateways"]["zone1"]["seq"] == 5
    assert [e["fault_type"] for e in snap["events"]] == ["crah_fan_failure"]
    assert snap["approvals"][0]["incident"] == "i1" and snap["approvals"][0]["commands"] == {"ups1": {"load_share": 0}}
    assert snap["kpis"]["latency_ms"] == 120.0 and snap["kpis"]["awaiting"] == 1
    with pytest.raises(ValueError):
        src.inject("crah_fan_failure")
