# Experiments (Step 7): E1 fault response and E4 robustness

Everything here runs without AWS through the **offline closed loop** (`experiments/closed_loop.py`):
the simulator, the detection engine, the deployed state-machine definition (run by a small ASL
interpreter), and the real remediation and approval Lambda code against mocked DynamoDB, SQS and
SNS. A subset is repeated on the **live local stack** (`tools/live_experiment.py`) to show that the
offline numbers carry over.

## Design

| | |
| --- | --- |
| Modes | **M1** alert only: static limits (D0), a simulated human reads the alert and carries out the playbook by hand. **M2** static limits + automated playbooks. **M3** ML hybrid (D2h) + automated playbooks (the proposed framework). |
| Comparisons | M1 vs M2 isolates the effect of **automation**; M2 vs M3 isolates the effect of **ML detection**. |
| Fault types | 8: CRAH fan failure, rack hotspot, chilled-water supply drift, pump degradation, stuck sensor, drifting sensor, UPS battery overheat (high risk), PDU overload (high risk). |
| Run | 10 min normal operation, then the fault, then 45 min observed. Scripted scenario actions are off; only the mode acts. |
| Seeds | 1001–1020, disjoint from training (101–108), threshold calibration (201–208) and the detector evaluation (11–15). All modes of a seed share the physical scenario and the human (paired design). |
| E1 | 8 faults × 3 modes × 20 seeds = **480 runs** (the proposal planned 7 × 3 × 20 = 420; the sensor fault was split into stuck and drifting). |
| M1 sensitivity | M1 with median human response of 5, 10, 20, 30 min × 8 faults × 10 seeds = 320 runs. |
| E4 load surge | Normal operation with a synchronised swing in one zone (all racks idle for 15 min, then all start a job at once) × 3 modes × 20 seeds = 60 runs. Any command is a false remediation. |
| E4 faulty sensor | A physical fault while a rack sensor in the same zone already failed 5 min earlier (CRAH 2 + stuck rack07; chilled-water drift + drifting rack12) × 3 modes × 10 seeds = 60 runs. |
| E4 message loss | 5, 10, 20 % of gateway messages lost × 8 faults × M2/M3 × 10 seeds = 480 runs. |

### The simulated human (M1, and approvals in M2/M3)

The response time is log-normal with a **median of 10 min** and σ = 0.5 (90 % between 4.4 and
22.8 min): the time to notice the alert, diagnose, and act on the building management system.
After it, the operator carries out the same playbook the automation would use, stage by stage,
2 minutes apart; they do not act on alerts the rules cannot explain. The same response time is used
when M2/M3 ask for approval of a high-risk plan, which is conservative for the automated modes
(approving a prepared plan is quicker than diagnosing and acting). Because the distribution is an
assumption, the M1 sensitivity suite varies its median from 5 to 30 min.

## Metrics (`experiments/metrics.py`)

All physical metrics use the simulator's **true** state, not the sensors, so no mode is credited
for what its own sensors or detectors believe.

| Metric | Definition |
| --- | --- |
| Detected, MTTD | The injected fault was diagnosed with the right type and target; time from fault start |
| Time to action | Fault start to the first command for this fault (playbook or human) |
| Time to recover (MTTR) | Fault start to the time the key value is back in its normal range **for good**. 0 = the value never left the range (the fault was contained before it did harm). Not recovered by the end = right-censored. |
| Limit exceeded | The key value left its normal range at some point |
| Exposure | Excess over the limit integrated over time, in the fault's own unit × minutes |
| Thermal exposure | Rack inlet above 27 °C, summed over all racks, K·min |
| Wrong actions | Incidents (or human actions) that commanded equipment for a fault that was not injected |
| False remediations (E4 surge) | Any command during normal operation |
| Alerts | Messages sent to humans, including approval requests and "mitigated" notices |

Normal range per fault: zone inlets ≤ 27 °C (CRAH failure), rack inlet ≤ 27 °C (hotspot), chilled
water ≤ setpoint + 1 K, total flow ≥ 35 L/s with running pumps ≤ 4.5 mm/s, UPS battery ≤ 35 °C,
PDU ≤ 90 %, and for sensor faults: the value used for decisions is quarantined or within 1 K of
the truth.

## Statistics (`experiments/analysis.py`)

Medians with 95 % bootstrap confidence intervals (2,000 resamples). Modes are compared per fault
type with two-sided Mann–Whitney U tests, Holm-corrected across the eight fault types, with the
rank-biserial correlation as effect size. Unrecovered runs count as the 45-minute window, which
ranks them worse than every recovered run; a median on a censored value is shown as "> 45".

## How to run

| Command | What it does | Time (8 workers) |
| --- | --- | --- |
| `make experiments` | All offline suites, then tables and figures | 48.6 min on the OCI server (7 workers) |
| `make e1` | Only E1 | about 12 min |
| `make analysis` | Tables, tests and figures from `experiments/results/runs.csv` | seconds |
| `make live-experiment` | 8 faults × 3 modes × 1 seed on the live stack at x10 | about 1 h 50 min |

Batches append to `experiments/results/runs.csv` and resume after an interruption. Options:
`EXP_SEEDS=20 WORKERS=7 SUITE=e1` for the offline batch, `LIVE_MODES=M3 LIVE_SEEDS=2` for the
live runs. Outputs: `e1_summary.md`, `e1_tests.md`, `m1_sensitivity.md`, `e4_summary.md`,
`live_vs_offline.md`, and the figures `fig_*.png` in `experiments/results/`.

## Results

From the full batch on the OCI server (1,400 runs, 7 workers, 48.6 min; `make experiments`).
Complete tables: `experiments/results/e1_summary.md`, `e1_tests.md`, `m1_sensitivity.md`,
`e4_summary.md`; figures `fig_e1_mttr.png`, `fig_e1_exposure.png`, `fig_m1_sensitivity.png`.
The runs are deterministic: a preliminary run of E1 during development gave identical medians.

### E1: fault response (median time to recover, minutes; 20 runs per cell)

| Fault | M1 alert only | M2 limits + automation | M3 ML + automation |
| --- | --- | --- | --- |
| CRAH fan failure | 11.5 | 1.0 | 1.0 |
| Rack hotspot | 11.8 | 0.8 | 0.8 |
| Chilled-water drift | 15.0 | 5.0 | 1.7 |
| Pump degradation | not detected (> 45) | not detected (> 45) | 0 (fixed before any limit) |
| Sensor drift | 23.2 | 13.3 | 2.3 |
| Sensor stuck | 0 (no harm; detected only by M3) | 0 | 0 |
| UPS battery overheat (approval) | 35.4 | 35.4 | 0 (contained) |
| PDU overload (approval) | 10.8 | 10.8 | 10.7 |

*0 = the value never left its normal range. Detection rate, time to detect, exposure and 95 %
confidence intervals are in `e1_summary.md`.*

- **Automation (M1 vs M2).** Recovery falls from 11–23 min to 1–13 min for the fault types handled
  without approval (Mann–Whitney U, Holm-adjusted p < 10⁻⁶, rank-biserial r ≈ 1). Thermal exposure
  after a CRAH failure falls from 641 to 17 K·min.
- **ML detection (M2 vs M3).** Faults that static limits see late or never are fixed earlier: pump
  wear (never detected by limits), chilled-water and sensor drift, and the UPS battery (detected at
  80 s instead of 13 min, so the approval arrives before the battery exceeds 35 °C).
- **Human-bound faults.** When approval is needed and detection is already fast (PDU overload), all
  modes take about the human response time: automation cannot beat the approval wait.
- **Safety.** No wrong actions in any run. The stuck sensor caused no harm in a steady hall (the
  frozen value stayed within 1 K of the truth); only detection separates the modes for that fault
  (0 % with limits, 100 % with ML).

### M1 sensitivity (all eight fault types, 10 seeds each)

| Median human response (min) | Recovered within 45 min | Median time to recover (min) |
| --- | --- | --- |
| 5 | 88 % | 10.3 |
| 10 | 85 % | 15.7 |
| 20 | 72 % | 28.4 |
| 30 | 57 % | 42.1 |
| M2 (no human for low/medium risk) | – | 5.0 |
| M3 (no human for low/medium risk) | – | 1.0 |

Even with a 5-minute human response, alert-only operation takes ten times longer to recover than
M3, so the comparison does not depend on the assumed response time.

### E4: robustness

| Stress | M1 | M2 | M3 |
| --- | --- | --- | --- |
| Load surges (20 runs): false remediations | 0 | 0 | 0 (1 notify-only alert per run) |
| CRAH failure with a stuck rack sensor: median recovery | 12.7 min | 1.0 min | 1.0 min |
| Chilled-water drift with a drifting sensor: median recovery | 16.7 min | 4.9 min | 1.7 min |

| Messages lost | M2 detected / recovered | M2 median MTTD, MTTR | M3 detected / recovered | M3 median MTTD, MTTR |
| --- | --- | --- | --- | --- |
| 5 % | 75 % / 85 % | 215 s, 5.8 min | 100 % / 100 % | 90 s, 1.7 min |
| 10 % | 75 % / 85 % | 275 s, 7.4 min | 100 % / 100 % | 100 s, 1.8 min |
| 20 % | 75 % / 82 % | 400 s, 13.6 min | 100 % / 99 % | 180 s, 3.4 min |

No wrong action in any of the 1,400 runs. With 20 % of messages lost, the ML detector still finds
every fault; detection slows because a gap in a gateway's sequence restarts its 90-second window.

### E2 and E3

Latency at scale (E2) and cost (E3) are measured on real AWS in Step 8: see
[aws.md](aws.md) and `experiments/results/e2_summary.md`, `e3_cost.md`, `e3_measured.md`.

## Threats to validity

- **Simulated plant.** Faults have idealised shapes and one severity each; real failures are
  noisier and overlap. The detector was validated separately on the real SKAB pump data (Step 4).
- **The human model is assumed.** The sensitivity suite shows how the M1 baseline moves with it.
  No operator skill, fatigue or wrong diagnosis is modelled, which favours M1.
- **Same playbooks in every mode.** M1's human uses the automated playbooks, so the comparison
  measures detection and response time, not the quality of the corrective action.
- **Offline vs live.** The offline loop has no network or service latency; the live fidelity runs
  quantify the difference (`live_vs_offline.md`).
- **Researcher bias.** Scenarios, thresholds, limits and the human model were fixed before the
  final runs and are published with the code.
