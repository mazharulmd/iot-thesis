# Anomaly detection (Step 4)

The detector Lambda runs once per gateway message. It decides whether each asset is
anomalous, diagnoses the fault, and publishes new anomalies to an EventBridge bus.
The deployed configuration is **D2h**: LSTM autoencoder + static limits + flatline rule.

```
gateway message ─► bridge / IoT rule ─► Detector Lambda
                                          │ 1. previous 8 messages of this gateway (Telemetry table)
                                          │ 2. per-asset signals → windows → detector → confirm (3 in a row)
                                          │ 3. diagnosis rules → fault type, target, playbook
                                          ├─► EventBridge bus "dc-selfheal-<stage>"  (AnomalyDetected)
                                          ├─► Detections table (evaluation record)
                                          └─► IngestStats table (heartbeat, latency)
EventBridge rule ─► SQS queue (inspection; Step 5 adds the remediation playbooks)
```

## Detectors compared

| Name | What decides "anomalous" | Trained on |
| --- | --- | --- |
| D0 | Static limits, like BMS alarms: inlet > 27 °C, CRAH fault, PDU > 90 %, chiller > 3 K above setpoint, pump vibration > 7.1 mm/s or flow < 20 L/s, battery > 35 °C | Nothing (fixed) |
| D1 | Isolation Forest on 60-s window features (last, mean, std, slope per signal) | Normal operation |
| D2 | LSTM autoencoder reconstruction error on 60-s windows | Normal operation |
| D1h / D2h | D1 / D2 **or** D0 limits **or** a flatline rule (a direct reading that did not change at all) | Normal operation |

One model of each kind per asset type (rack, CRAH, PDU, chiller, pump, UPS), shared by all assets of that type.

**Confirmation:** an asset is confirmed anomalous when 3 consecutive windows (30 s) are anomalous.
An event is sent when an asset becomes anomalous, and again only if its diagnosis changes.

**Diagnosis (shared by all detectors, so experiments compare detection only):**

| Asset | Rule (z-score above 3 **and** a physically meaningful deviation) | Fault |
| --- | --- | --- |
| any | A direct reading did not change within the window | `sensor_stuck` |
| rack | Hotter than zone peers by ≥ 1 K, and the rack's air temperature rise shrank by about the same amount | `sensor_drift` |
| rack | Hotter than zone peers by ≥ 1 K, outlet rose too | `rack_hotspot` |
| rack | All racks warm, approach to supply air normal | suppressed (plant's fault) |
| CRAH | Status not "on" or fan stopped | `crah_fan_failure` (suppresses its zone's hot-rack events) |
| PDU | Load > 90 % or unusually high | `pdu_overload` |
| chiller | Supply ≥ 1 K above setpoint and unusual | `chw_supply_drift` |
| pump | Vibration, current or current-per-flow up, or flow down, beyond noise | `pump_degradation` |
| UPS | Battery ≥ 1 K warmer than normal and unusual | `ups_battery_overheat` |
| any | Anomalous but no rule fits | `unexplained` → notify a human, never automate |

The absolute minimums were added after evaluation showed that z-scores alone let sensor
noise on a secondary signal decide the fault type (e.g. 0.3 K of noise diagnosed as a hotspot).

## Training (`make train`, about 2 minutes)

- 8 × 6 h of simulated normal operation for training, 8 × 6 h for validation (different seeds).
- No fault data is used for training or thresholds.
- Isolation Forest: scikit-learn, 100 trees, 256 samples per tree; exported to arrays and scored in NumPy (identical scores, checked by a test).
- LSTM autoencoder: encoder LSTM (16 units) → latent (2–4) → decoder LSTM (16) → linear; trained with JAX (Adam, 15 epochs). The same forward function runs in NumPy inside the Lambda (checked by a test).
- Thresholds: the 99.99th percentile of each asset type's validation scores.

## Results on simulated faults (`make evaluate`)

8 fault types × 5 seeds, no remediation; 24 h of separate normal operation for false alarms.
Seeds differ from training and validation.

| Fault | D0 | D1 | D2 | D1h | D2h |
| --- | --- | --- | --- | --- | --- |
| crah_fan_failure | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s |
| sensor_stuck | 0/5 | 1/5 · 2620 s | 0/5 | 5/5 · 70 s | 5/5 · 70 s |
| sensor_drift | 5/5 · 780 s | 5/5 · 440 s | 5/5 · 120 s | 5/5 · 440 s | 5/5 · 120 s |
| pump_degradation | 0/5 | 5/5 · 1380 s | 5/5 · 170 s | 5/5 · 1380 s | 5/5 · 170 s |
| chw_supply_drift | 5/5 · 280 s | 5/5 · 130 s | 5/5 · 90 s | 5/5 · 130 s | 5/5 · 90 s |
| rack_hotspot | 5/5 · 30 s | 2/5 · 2930 s | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s |
| ups_battery_overheat | 5/5 · 800 s | 5/5 · 160 s | 5/5 · 80 s | 5/5 · 160 s | 5/5 · 80 s |
| pdu_overload | 5/5 · 40 s | 0/5 | 5/5 · 30 s | 5/5 · 40 s | 5/5 · 30 s |

| Detector | Detected | Median time to detect | Wrong automated events | Automated false alarms / day | Notify-only false alarms / day |
| --- | --- | --- | --- | --- | --- |
| D0 | 30/40 | 155 s | 0 | 0 | 0 |
| D1 | 28/40 | 195 s | 0 | 0 | 2 |
| D2 | 35/40 | 80 s | 0 | 0 | 1 |
| D1h | 40/40 | 75 s | 0 | 0 | 2 |
| **D2h** | **40/40** | **75 s** | **0** | **0** | **1** |

Findings for RQ2:

- Static limits miss slow degradation that never crosses a limit (pump wear) and data-quality faults (stuck sensor), and are 3–10 times slower on gradual faults.
- Pure ML misses flatlined sensors (a frozen value looks normal) and, for the Isolation Forest, values far outside the training range (PDU overload); combining ML with limits and a flatline rule covers all faults.
- Threshold sensitivity (sweep in `detection/results/sweep/`): raising the quantile from 0.999 to 0.9999 cut notify-only false alarms from ~13–15 to 1–2 per day. D2h kept the same detection times; D1h became much slower. The LSTM autoencoder is more robust to threshold choice.

## External validation on real data (`make skab`)

SKAB water-pump testbed, 34 labelled experiments, leaderboard protocol (first 400 rows of each
experiment for training, the rest for testing, pointwise scoring):

| Detector | F1 | False alarm rate | Missed alarm rate |
| --- | --- | --- | --- |
| D0 ±3σ limits | 0.76 | 44.1 % | 15.4 % |
| D1 Isolation Forest | 0.50 | 13.2 % | 63.1 % |
| D2 LSTM autoencoder | 0.77 | 55.9 % | 7.4 % |
| D2h hybrid | 0.77 | 58.2 % | 6.8 % |
| *SKAB leaderboard: LSTM-AE* | *0.74* | *29.96 %* | *25.92 %* |
| *SKAB leaderboard: Isolation forest* | *0.29* | *2.56 %* | *82.89 %* |

The detector families reach F1 comparable to or above the published baselines on real pump data.
Their false alarm rate on SKAB is higher, because thresholds come from only ~400 training rows per
experiment; this should be stated as a limitation.

## Commands

| Command | What it does |
| --- | --- |
| `make train` | Train D1/D2 and write `detection/models/` |
| `make evaluate` | Offline evaluation (about 3 min); writes `detection/results/offline_*` |
| `make skab` | SKAB validation (about 2 min); downloads the data on first use |
| `make build-lambdas` | Package the detector (code + bundle + Linux NumPy) into `build/detector/` |
| `make deploy-local` | Builds and deploys all stacks |
| `make events` / `make events F=1` | Show anomaly events from the queue |
| `make warm` | Pre-warm the detector Lambda (also done by `make pipeline-up`) |
| `make e2e` | End-to-end check including a live CRAH failure (prints the latency split) |
| `make latency` | Latency split at x1/x5/x10 (about 6 min); `SPEEDS=1,10 WINDOW=120` to change |

Use another detector in the Lambda with `cdklocal deploy --all -c stage=local -c detector=d1h`.

## Latency

Every message records, in the IngestStats table, how long it took from the gateway's `sent_at`
to the end of the detector run, split into four parts:

| Part | What it covers |
| --- | --- |
| to bridge | MQTT delivery until the bridge (IoT rule) receives the message |
| bridge | storing the message in DynamoDB and the asynchronous Lambda invoke call |
| queue | the Lambda service's asynchronous queue and container dispatch |
| handler | inside the Lambda: history query, detection, publishing |

The bridge stamps `bridge_rx_ms` / `bridge_tx_ms` on the invoke payload (on AWS, the IoT rule's
`timestamp()` does the same job). The bridge runs one worker per gateway, like IoT Core runs rule
actions in parallel, while keeping each gateway's messages in order.

`make latency` runs normal operation at x1, x5 and x10 (0.5, 2.5 and 5 msg/s) and writes
`runs/latency/summary.md`. `make e2e` prints the same split as information only.
The first invocation after `make up` is a cold start (runtime image + NumPy + model bundle);
`make warm`, `make pipeline-up`, `make e2e` and `make latency` warm the Lambda first.

Measured on the OCI server (4 OCPU, LocalStack, detector D2h), 60-s windows:

| Speed | Messages/s | Latency ms (1st -> 2nd half) | To bridge | Bridge | Queue | Handler | of which history query | of which detection | Backlog |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| x1 | 0.5 | 106 (105 -> 107) | 4 | 27 | 30 | 44 | 41 | 3.1 | none |
| x5 | 2.5 | 202 (204 -> 200) | 5 | 126 | 29 | 43 | 40 | 3.2 | none |
| x10 | 5.0 | 271 (257 -> 285) | 4 | 194 | 32 | 41 | 38 | 3.2 | 2 s drain |

After LocalStack was set to save state only on shutdown (Step 5.1; previously a snapshot every
15 s locked DynamoDB while saving), the same x10 measurement gave **108 ms** (107 -> 108 ms within the
window): to bridge 5, bridge 30, queue 28, handler 45 (history query 42, detection 3.3).
The table above is therefore an upper bound caused by the emulator's persistence setting.

- The pipeline keeps up at 10x the real message rate; latency does not grow within a window.
- Detection itself takes about 3 ms; the handler's time is almost all the DynamoDB history query.
- The part that grows with load is the bridge's calls into LocalStack (DynamoDB write + invoke API),
  i.e. the emulator, not the design. Step 8 repeats this on real AWS for comparison.
- Right after a start, LocalStack starts extra Lambda containers under load, which briefly adds
  seconds of delay; warming 10 containers first (`make warm`) avoids most of it.

**History is run-safe:** the detector only uses previous messages with the expected sequence
numbers at the expected times. A fast run (x10) writes timestamps ahead of the wall clock, and
without this rule a run started soon after it mixed the two runs' data into its windows.

## Limitations

- Faults are simulated with idealised shapes; real failures are noisier and can overlap.
- Diagnosis rules are hand-written from equipment physics; they are transparent but must be extended for new fault types.
- Correlation across gateways (e.g. a chiller fault warming every zone) is left to the incident layer in Step 5.
- The Lambda keeps no state; history comes from the Telemetry table, so detection needs about 90 s of data after a restart.
