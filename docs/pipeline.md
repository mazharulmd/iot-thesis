# Telemetry pipeline (Step 3)

Five simulated gateways publish over MQTT. Their messages are stored, sent to a
Lambda, and commands flow back to the devices through device shadows.

```
simulator.live (5 gateways)
    │  dc/hall1/<gw>/telemetry  (every 10 s)
    ▼
Mosquitto ──► bridge ──► DynamoDB  Telemetry      (rule 1, 30-day TTL)
                    ├──► Lambda    Detector       (rule 2, async; see detection.md)
                    └──► S3        iot-errors/     (failures)
    ▲
    │  $aws/things/<gw>/shadow/update/delta   (commands to the device)
bridge shadow emulator ◄── $aws/things/<gw>/shadow/update  (desired from tools/Lambda,
                                                            reported from the device)
```

| Local piece | Real AWS equivalent |
| --- | --- |
| Mosquitto | AWS IoT Core message broker |
| `bridge` rules | IoT topic rules (DynamoDBv2 action, Lambda action, S3 error action) |
| `bridge` shadow emulator | AWS IoT device shadows (same topic names) |
| DynamoDB, Lambda, S3 on LocalStack | The same services on AWS |

The bridge is only for local use. On AWS, IoT Core does its jobs natively.

## Message formats

Telemetry (one per gateway every 10 simulated seconds):

```json
{"gw": "zone2", "ts": "2026-09-29T10:00:00.000Z", "seq": 18, "sent_at": "2026-09-29T10:00:00.004Z",
 "assets": {"rack07": {"t_in": 20.61, "t_out": 35.2, "p_kw": 40.2}, "crah2": {"fan_pct": 62.5, "status": "on"}}}
```

- `ts` is simulated time; `sent_at` is the wall-clock publish time used for latency.
- The bridge adds `received_at` and `ttl` before storing.

Command (desired state written to the gateway's shadow):

```json
{"state": {"desired": {"crah1": {"fan_pct": 70}, "cmd_id": "inc-0412-a1", "issued_at": "..."}}}
```

The device applies it and reports back on the same topic:

```json
{"state": {"reported": {"crah1": {"fan_pct": 70.0}, "cmd_id": "inc-0412-a1", "applied_at": "..."}}}
```

Unsupported commands are reported under `errors`, so the sender knows they failed.

**Commands sent while a gateway is offline are not lost.** On every connect or reconnect, each
gateway publishes to `$aws/things/<gw>/shadow/get` and applies the `delta` in the answer on
`.../shadow/get/accepted`. This is the standard AWS IoT device pattern, and it also covers
network drops during the robustness experiment (E4).

**Clean runs.** `make pipeline-up` clears all shadows before starting the simulator, so commands from
an earlier run cannot leak into a new one (`make reset-shadows` does the same by hand). The bridge saves
shadows to `.bridge/shadows.json` and reloads them after a restart.

## Commands

| Command | What it does |
| --- | --- |
| `make deploy-local` | Builds the detector and deploys Foundation, Data and Detection stacks to LocalStack |
| `make pipeline-up` | Starts bridge, clears shadows, starts the live simulator and waits until it is connected (`SPEED=10` for 10x) |
| `make status-pipeline` | Messages stored, Lambda invocations, latency, shadow state per gateway |
| `make cmd A=crah1 D='{"fan_pct": 70}'` | Sends a command and waits for the device to report it |
| `make pipeline-down` | Stops bridge + live simulator |
| `make reset-shadows` | Clears all gateway shadows |
| `make e2e` | Automated Step 3 check; starts and stops its own pipeline |

Run a fault scenario live (commands will come from the remediation layer in Step 5):

```bash
.venv/bin/python -m simulator.live --scenario simulator/scenarios/crah_fan_failure.yaml --speed 10
```

Ground truth for each live run is written to `runs/live-<scenario>-<time>/` (`labels.json`,
`commands.jsonl`), never to MQTT.

## Tables

| Table | Key | Contents |
| --- | --- | --- |
| Telemetry | `gw` + `ts` | Full gateway message, `received_at`, `ttl` |
| IngestStats | `gw` | `msg_count`, `last_seq`, `last_seen_ms`, `last_latency_ms`, `latency_sum_ms` |

The mean latency includes Lambda cold starts (the first invocations after a deploy or idle period), so it
reads high at first. `last_latency_ms` shows warm performance. Proper latency percentiles are measured in experiment E2.

Provisioned capacity totals stay within DynamoDB's always-free 25 WCU / 25 RCU (checked by a test).

## Bridge concurrency (Step 4.2)

Telemetry rules run on one worker thread per gateway, off the MQTT network thread, so a slow
DynamoDB write or Lambda invoke for one gateway does not hold up the others or shadow commands.
Order within a gateway is kept. The bridge log reports the rule backlog every minute (`backlog=`).
