# Live end-to-end check on AWS (eu-north-1), 19.11.2026

`make aws-check` on stage `dev`, run from an EC2 instance in eu-north-1 (the simulated gateways
connected to IoT Core over MQTT with an X.509 certificate). Simulator speed ×10.

## CRAH failure (tools.e2e_check)

| Check | Result |
| --- | --- |
| detector Lambda warm-up | INFO: 10 containers in 1.4 s |
| command sent while offline applied on connect | PASS: crah3 fan_pct=65 via shadow get |
| command crah1 fan_pct=70 applied via shadow | PASS: round trip 253.7 ms |
| telemetry stored for zone1–4 and plant | PASS: 82 messages each |
| detector Lambda invoked for zone1–4 and plant | PASS: 82 messages each |
| latency send → detector done (×10 load) | INFO: mean 85 ms, p95 ≤ 150 ms = to bridge 12 + bridge 0 + queue 61 + handler 13 (history query 7, detection 6.1) over 105 msgs |
| anomaly event crah_fan_failure/crah2 published | PASS: 30 s simulated after the fault |
| no automated anomaly before the fault | PASS: none |
| playbook mitigated crah2 failure, no human input | PASS: verified 260 s simulated after the fault |
| sensor message → first command at the gateway | INFO: 2,399 ms (detect, decide, act through the shadow) |
| standby crah5 running in zone 2 | PASS: status on, zone 2, fan 59 % |
| zone 2 rack inlets back below 27 °C | PASS: max 20.8 °C |
| no incident escalated | PASS: none |

Incident `20261119T091407-crah2-2e10` (wall-clock times; 2 related notify-only events joined it):
opened 09:09:11 → precheck_passed 09:09:12 → act "boost neighbours and start standby" 09:09:13 →
verified 09:09:23 → act "hand neighbours and standby to automatic control" 09:09:23 → verified
09:09:33 → closed 09:09:34 ("Repair crah2 (zone 2); standby in service."). SNS email
"Mitigated: cooling_unit_failover on crah2" received.

END-TO-END CHECK PASSED

## UPS overheating with human approval (tools.e2e_approval)

| Check | Result |
| --- | --- |
| high-risk plan waits for approval | PASS: status awaiting_approval |
| nothing sent while waiting | PASS: ups1 still carries 374 kW |
| approval link opens the plan (GET decides nothing) | PASS: HTTP 200 |
| approved with a POST to the function URL | PASS: HTTP 200 |
| link cannot be used twice | PASS: HTTP 409 |
| plan rechecked on fresh telemetry after approval | PASS |
| load transferred and verified | PASS: status mitigated |
| ups1 load now near zero | PASS: ups1 0 kW, ups2 730 kW |

Incident `20261119T091613-ups1-160d`: opened 09:10:40 → precheck_passed 09:10:41 →
approval_requested 09:10:41 → rechecked_after_approval 09:10:49 → act "transfer load from ups1 to
ups2" 09:10:49 → verified 09:10:59 → closed 09:10:59. SNS email "APPROVAL NEEDED: ups_load_transfer
on ups1" received with the one-time link (expires in 30 minutes); opening the link afterwards showed
"This request was already handled (approved)."

APPROVAL CHECK PASSED
