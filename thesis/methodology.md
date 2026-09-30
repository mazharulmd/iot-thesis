# Methodology and evaluation criteria

Sep 30, 2026 · @Mazharul Islam Tusar

The framework already meets the problem statement's core target in simulation and on LocalStack: automated, guarded remediation cuts recovery from 11–23 min to 1–13 min with no wrong actions in 1,400 runs. The claim becomes complete only after Step 8 measures latency, scalability and cost on real AWS against the criteria fixed below.

## Does the work meet the problem statement?

Three of the six parts of the target are met now, two are met with caveats, and one depends on Step 8. The problem statement asks for "a validated, cloud-native way to go from IoT sensor data to safe, automatic corrective action within seconds" and names three gaps.

| Part of the target | Evidence so far | Status |
| --- | --- | --- |
| Gap 1: slow, manual response | E1: median time to recover falls from 11–23 min (M1) to 1–13 min (M2) for low and medium-risk faults, Holm-adjusted p < 10⁻⁶. Thermal exposure after a CRAH failure falls from 641 to 17 K·min. Holds for human response medians of 5–30 min (M1 sensitivity). | Met (simulation) |
| Gap 2: noisy detection | ML hybrid (D2h) detects all 8 fault types; static limits miss pump wear and stuck sensors. Drifts are caught 3–6× earlier (sensor drift 790 s → 130 s). No automated action during load surges. On real pump data (SKAB), D2h matches thresholds on F1 (0.77 vs 0.76) but raises more false alarms. | Partly met: the advantage is on slow drifts, not overall accuracy |
| Gap 3: unsafe automation | Locks, risk tiers, approval with one-time links, recheck, verification, rollback, circuit breaker and rate limit, each covered by tests. Zero wrong actions in 1,400 runs, including faulty sensors and 20 % message loss. | Met (simulation, LocalStack) |
| Cloud-native, serverless | Five CDK stacks: IoT Core, Lambda, EventBridge, Step Functions, DynamoDB, SNS. Deployed and checked end to end on LocalStack. | Met locally; real AWS in Step 8 |
| "Within seconds" | Pipeline from gateway to detector ≈ 0.1 s on LocalStack. Fault to first command is 30 s for abrupt faults and 1.5–3 min for drifts: the 10 s message period and 3-window debounce set a 30 s floor. | Met for the pipeline; the thesis must state the 30 s detection floor |
| "Validated", including scalability and cost | Latency on real AWS, the 50 / 500 / 2,000-gateway load test and the measured bill are not yet run. | Open: Step 8 |

**Verdict:** the main target is achievable, and the hardest part (showing that guarded automation recovers faster without unsafe actions) is already shown. Two claims need care in the writing: ML detection is better for slow drifts, not better overall, and "within seconds" applies from detection to action, not from fault onset.

## Research design

The thesis is Design Science Research: the framework is the artefact, and it is evaluated against measurable requirements derived from the problem statement. It follows the six-step process of Peffers et al. (2007) and the guidelines of Hevner et al. (2004).

| DSR step | What it is in this thesis | Output | Chapter |
| --- | --- | --- | --- |
| 1. Problem | Outage causes, manual response, gaps in self-healing research for the facility layer | Problem statement, 3 gaps | 1–2 |
| 2. Objectives | Gaps turned into testable requirements and hypotheses H1–H8 (next section) | Acceptance criteria | 3 |
| 3. Design and development | Simulator, detectors, playbooks and guardrails, 5 CDK stacks | Code in the repository | 3–4 |
| 4. Demonstration | Closed-loop fault runs, offline and on the live local stack; end-to-end check on real AWS | Runs, logs | 5 |
| 5. Evaluation | E1–E4 and detector validation on SKAB, judged against H1–H8 | Results chapter | 6 |
| 6. Communication | Thesis, public repository, optional paper | Thesis | 7–8 |

**Evaluation strategy.** Following the FEDS framework (Venable et al., 2016), the evaluation is *ex post* and *artificial*: the finished artefact is tested in controlled experiments with a simulated plant, not in a live facility. This choice fits because injecting faults into real cooling and power equipment is unsafe, and it gives known ground truth for every fault. Realism is added in two steps: detectors are checked on real pump data (SKAB), and the cloud path is measured on real AWS.

**Unit of analysis.** One run = one fault injected into the simulated data hall, observed for 45 minutes, under one operating mode. The three modes isolate the two design choices: M1 vs M2 measures the effect of automation, and M2 vs M3 measures the effect of ML detection.

## Hypotheses and acceptance criteria

Each hypothesis tests one requirement from the problem statement; the target is fulfilled when H1–H8 all pass. H1–H5 already have results. H6–H8 are fixed here, before Step 8 runs, so they cannot be tuned to the outcome.

| # | Requirement (gap) | Hypothesis | Metric and test | Pass criterion | Result |
| --- | --- | --- | --- | --- | --- |
| H1 | Faster response (gap 1) | Automation shortens recovery | MTTR, M1 vs M2, Mann–Whitney U, Holm-corrected | M2 better (p < 0.05) for every fault that harms the hall and that limits can detect | **Pass:** 4 of 4 such faults, p < 10⁻⁶, r ≥ 0.97 |
| H2 | Better detection (gap 2) | ML detects more faults, and slow ones earlier | Detection rate; MTTR, M2 vs M3, same test | M3 detects every fault type; better MTTR for slow-developing faults | **Pass:** 8 of 8 types; better for the 4 slow-developing faults (p < 10⁻⁵); equal for step faults |
| H3 | Fewer false alarms (gap 2) | ML adds no false actions in normal operation | Automated actions in surges and 24 h normal runs; notify-only alerts per day | 0 automated false actions; ≤ 2 notify-only alerts per hall per day | **Pass:** 0 actions; 1.0 alert per day (D2h) |
| H4 | Detection works on real data (gap 2) | The detector generalises beyond the simulator | F1 and false-alarm rate on the SKAB test set | F1 ≥ thresholds (D0) and within 0.05 of the best published outlier detector (0.78) | **Pass on F1** (0.77 vs 0.76); false-alarm rate 53 % vs 40 %, reported as a limitation |
| H5 | Safe automation (gap 3) | Guardrails prevent harmful or conflicting actions | Wrong actions across all runs; guardrail tests | 0 wrong actions; every guardrail exercised by a test; approval shown end to end | **Pass:** 0 in 1,400 runs; 121 tests; approval check on LocalStack |
| H6 | Within seconds | The cloud path adds only seconds to a decision | Sensor message → first command at the gateway, p95, real AWS | ≤ 5 s end to end; ≤ 1 s gateway → detector | Open (Step 8); LocalStack ≈ 0.1 s |
| H7 | Scalable | The same design serves a large facility | p95 latency, messages processed, Lambda throttles at 50 / 500 / 2,000 gateways | p95 ≤ 1 s and ≥ 99.9 % processed at every level; throttles only from the account quota, with the concurrency needed for 10,000 gateways stated | Open (Step 8) |
| H8 | Affordable | Running cost is small next to the hall it protects | Monthly cost model with measured usage; Cost Explorer bill | ≤ $1 per rack per month at list price; measured test bill within ±30 % of the model | Open (Step 8); model with default usage: $0.32 per rack |

**Why these thresholds.** 5 s is a sixth of the 30 s detection floor, so the cloud path never dominates the response. $1 per rack is under 0.1 % of a GPU rack's power bill (45 kW × 730 h × $0.10/kWh ≈ $3,300 per month at full load). 2 alerts per day is chosen as a rate one on-shift operator can review; it is an assumption and is stated as one.

**Honesty note for the thesis.** The comparisons and tests behind H1–H2 were fixed in the proposal before any run. The numeric pass criteria for H3–H5 are written after the results and must be presented as such. H6–H8 are pre-registered by this document.

## Evaluation protocol

Six evaluations cover the hypotheses; the first four are done, the last two run in Step 8.

| Evaluation | Tests | Environment | Design | Runs | Status |
| --- | --- | --- | --- | --- | --- |
| Detector evaluation | H2, H3 | Offline simulator | 5 detectors × 8 faults × 5 seeds, plus normal operation | 40 per detector | Done |
| SKAB validation | H4 | Real pump testbed data | Published train/test split, 34 test experiments | 5 detectors | Done |
| E1 fault response | H1, H2, H5 | Offline closed loop (real Lambda code, mocked AWS) | 8 faults × 3 modes × 20 seeds, paired by seed | 480 | Done |
| M1 sensitivity and E4 robustness | H1, H3, H5 | Offline closed loop | Human median 5–30 min; load surges; faulty sensors; 5–20 % message loss | 920 | Done |
| Live check and E2 load test | H5, H6, H7 | Real AWS, ap-south-1 | End-to-end fault and approval check; 50, 500, 2,000 gateways × 30 min | 1 + 3 | Step 8 |
| E3 cost | H8 | Real AWS bill + cost model | Measured usage per message → 1, 10, 100 halls | – | Step 8 |

**Data separation.** Detectors are trained on normal operation only (seeds 101–108); thresholds are calibrated on seeds 201–208; the detector evaluation uses seeds 11–15 and the experiments seeds 1001–1020. No fault data is used for training, and ground-truth labels never enter the cloud path.

**Fixed before the final runs.** Fault definitions, detector thresholds, playbooks, the simulated human, run length (10 min warm-up, 45 min observed) and all seeds were frozen before the 1,400-run batch. The batch is deterministic: a repeat gave identical medians.

**Offline vs cloud.** The offline closed loop runs the deployed state-machine definition and the real Lambda handlers against mocked AWS services. A subset on the live local stack and the Step 8 check on real AWS show that the offline numbers carry over.

## Analysis

Results are reported as medians with 95 % bootstrap confidence intervals (2,000 resamples), because recovery times are skewed and partly censored.

- **Comparisons:** two-sided Mann–Whitney U tests per fault type, Holm-corrected across the 8 fault types, with rank-biserial r as effect size. A mode is "better" only when the adjusted p < 0.05.
- **Censoring:** a run not recovered within 45 min counts as 45 min, which ranks it below every recovered run; such medians are shown as "> 45".
- **Physical truth:** recovery and exposure use the simulator's true state, never the sensors, so no mode is credited for what its own detectors believe.
- **Latency (E2):** p50, p95 and p99 from per-message timestamps, per load level; the 10,000-gateway figure is an extrapolation and is labelled as one.
- **Cost (E3):** list prices for ap-south-1, with and without the always-free allowances; the measured bill checks the model at test scale.

## Threats to validity

The largest threat is that the plant is simulated; the thesis must say so plainly and limit its claims to what the evidence supports.

| Threat | Type | How it is handled |
| --- | --- | --- |
| Simulated plant: idealised faults, one severity and one target per fault type | External | Reduced-order model with an energy-balance test; a source cited for each key parameter in chapter 4; claims framed as "in a simulated hall"; optional severity sweep (next section) |
| Detectors trained and tested on the same simulator | Construct | Training on normal data only, disjoint seeds, and SKAB as an independent real-data check |
| ML false alarms on SKAB higher than thresholds | Conclusion | Reported openly; hybrid rules and 3-window debouncing keep automated false actions at 0 in the simulated hall |
| Assumed human response in M1 | Internal | Sensitivity over medians of 5–30 min; conclusion unchanged at 5 min |
| Synthetic IT load instead of the Alibaba GPU trace named in the proposal | External | Stated as a deviation; load surges (E4) stress the detector with the worst-case synchronised swing |
| LocalStack is not AWS | Construct | Step 8 repeats the end-to-end check and measures latency and cost on real AWS |
| Pass criteria for H3–H5 set after the results | Conclusion | Stated as post hoc; H6–H8 fixed before Step 8 |
| Single cloud, single region | External | Portability discussed, not tested |
| Researcher bias | Internal | Scenarios, seeds and thresholds frozen before the final batch; all code, data and results in the public repository |

## Remaining work to fulfil the target

Step 8 is the only item that decides whether the target is met; the others strengthen the thesis against the threats above.

- [ ] **Step 8 on real AWS** (decides H6–H8): end-to-end check, E2 load test at 50 / 500 / 2,000 gateways, E3 cost model and measured bill. Set a $10 AWS budget alert first.
- [ ] **CloudWatch dashboard** (in the proposal's scope, not yet built): one dashboard for telemetry rate, detector latency, incidents and throttles, added to the CDK app before Step 8 so the load test is visible live. Free within the 3-dashboard allowance.
- [ ] **Severity sweep** (external validity, optional, offline): each fault at 3 severities × 3 modes × 10 seeds = 720 runs, about 25 min on the server. Shows whether the M1/M2/M3 ranking holds for milder and harsher faults.
- [ ] **Simulator parameter sources:** cite a published value or standard for each key parameter in `simulator/config.py` (ASHRAE limits, CRAH airflow per kW, pump vibration limits, battery thermal limits).
- [ ] **Literature check:** verify the gap table (proposal §4.4) in Scopus or IEEE Xplore, as the proposal requires.
- [ ] **Write the thesis** using this document as chapter 5 (method) and the hypothesis table as the backbone of chapter 6 (results).

## References

- Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. *MIS Quarterly*, 28(1), 75–105. [doi:10.2307/25148625](https://doi.org/10.2307/25148625)
- Peffers, K., Tuunanen, T., Rothenberger, M. A., & Chatterjee, S. (2007). A design science research methodology for information systems research. *Journal of Management Information Systems*, 24(3), 45–77. [doi:10.2753/MIS0742-1222240302](https://doi.org/10.2753/MIS0742-1222240302)
- Venable, J., Pries-Heje, J., & Baskerville, R. (2016). FEDS: a framework for evaluation in design science research. *European Journal of Information Systems*, 25(1), 77–89. [doi:10.1057/ejis.2014.36](https://doi.org/10.1057/ejis.2014.36)
- Katser, I. D., & Kozitsin, V. O. (2020). Skoltech Anomaly Benchmark (SKAB). [github.com/waico/SKAB](https://github.com/waico/SKAB)
- Results cited in this document: `experiments/results/` and `detection/results/` in [mazharulmd/iot-thesis](https://github.com/mazharulmd/iot-thesis).
