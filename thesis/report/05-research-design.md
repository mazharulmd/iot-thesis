# Research design and methods

This chapter describes how the research was carried out: the research approach, the requirements and hypotheses against which the framework was evaluated, the experiments, the data, and the methods of analysis.

## Design Science Research

The thesis followed Design Science Research (DSR). In DSR, knowledge is produced by building an artefact that solves a practical problem and by evaluating it rigorously against that problem (Hevner, March, Park & Ram 2004). The approach was chosen because the research questions concern the design of a system and its measured effect, not the description of an existing phenomenon. A purely empirical study, such as a survey of operators, could have described how faults are handled today, but it could not have shown whether a specific design shortens recovery without unsafe actions.

The work was organised according to the six activities of the DSR methodology of Peffers, Tuunanen, Rothenberger and Chatterjee (2007). Table 2 shows how each activity was carried out in this thesis.

Table 2. Design Science Research activities in this thesis

| DSR activity | Content in this thesis | Output | Chapter |
| --- | --- | --- | --- |
| 1. Identify the problem | Outage causes, manual response, gaps in self-healing research for the facility layer | Problem statement and three gaps | 1, 2, 4 |
| 2. Define objectives | Gaps turned into testable requirements and hypotheses H1–H8 | Acceptance criteria | 5 |
| 3. Design and develop | Simulator, detectors, playbooks, guardrails, cloud infrastructure | Source code in the repository | 6 |
| 4. Demonstrate | Closed-loop fault runs offline and on the local cloud emulator | Runs, logs, audit trails | 6, 7 |
| 5. Evaluate | Detector evaluation, external validation, experiments E1–E5 | Results judged against H1–H8 | 7 |
| 6. Communicate | Thesis report and public source code | This report | 8 |

The evaluation was *ex post*, because the finished artefact was evaluated, and *artificial*, because it was tested in controlled experiments with a simulated plant rather than in a live facility. According to the Framework for Evaluation in Design Science (FEDS), an artificial evaluation is appropriate when the main risk is technical and when testing with real users or systems would be costly or unsafe (Venable, Pries-Heje & Baskerville 2016). Both conditions applied: injecting faults into real cooling and power equipment is not acceptable, and a simulator provides exact ground truth for every fault. Realism was added in two steps: the detectors were also evaluated on real pump data, and the cloud path was designed to be measured on real AWS.

## Requirements and hypotheses

The problem statement was "data center facility operations lack a validated, cloud-native way to go from IoT sensor data to safe, automatic corrective action within seconds". It contains three gaps (slow manual response, noisy detection, and unsafe automation) and three further requirements (a cloud-native design, a response within seconds, and validation including scalability and cost). Each requirement was turned into a hypothesis with a measurable pass criterion. Table 3 lists the hypotheses.

Table 3. Hypotheses and pass criteria

| # | Requirement | Hypothesis | Pass criterion |
| --- | --- | --- | --- |
| H1 | Faster response | Automation shortens recovery | M2 recovers faster than M1 for every harmful fault that limits can detect (Holm-adjusted p < 0.05) |
| H2 | Better detection | ML detects more faults, and slow faults earlier | M3 detects all fault types; M3 recovers faster than M2 for slow-developing faults |
| H3 | Fewer false alarms | ML adds no false actions in normal operation | 0 automated false actions; ≤ 2 notify-only alerts per hall per day |
| H4 | Real-data validity | The detector generalises beyond the simulator | SKAB F1 ≥ static limits and within 0.05 of the best published outlier detector |
| H5 | Safe automation | Guardrails prevent harmful or conflicting actions | 0 wrong actions in all runs; every guardrail exercised by a test; approval shown end to end |
| H6 | Within seconds | The cloud path adds only seconds | Sensor message to first command at the gateway ≤ 5 s (p95) on AWS |
| H7 | Scalable | The design serves a large facility | p95 latency ≤ 1 s and ≥ 99.9 % of messages processed at 50, 500 and 2,000 gateways |
| H8 | Affordable | Running cost is small compared with the hall | ≤ $1 per rack per month at list price; measured bill within ±30 % of the cost model |

The modes M1–M3 are defined in Section 5.3. The 5-second limit in H6 is one sixth of the 30-second detection floor of the design (Section 6.5), so that the cloud path never dominates the response time. The cost limit in H8 is less than 0.1 % of the electricity cost of one GPU rack. The comparisons behind H1 and H2 were fixed in the research proposal before any experiment was run. The numeric criteria of H3–H5 were written after the results were known and are therefore reported as post hoc. The criteria of H6–H8 were fixed before the corresponding measurements.

## Operating modes

Three operating modes were compared:

- **M1 – alert only.** Static limits (detector D0) raise an alert, and a simulated operator responds after a delay and carries out the playbook by hand.
- **M2 – limits and automation.** The same static limits trigger the automated playbooks.
- **M3 – machine learning and automation.** The hybrid ML detector (D2h) triggers the automated playbooks. This is the proposed framework.

Comparing M1 with M2 isolates the effect of automation, because both use the same detector. Comparing M2 with M3 isolates the effect of machine-learning detection, because both use the same automation. In all modes the operator, or the automation, used the same playbooks, so the experiments measured detection and response time rather than the quality of the corrective action.

The simulated operator's response time followed a log-normal distribution with a median of 10 minutes and σ = 0.5, so that 90 % of responses fell between about 4 and 23 minutes. The response time covered noticing the alert, diagnosing the fault and acting through the management system. The same distribution was used when the automated modes requested approval of a high-risk action, which is conservative for M2 and M3, because approving a prepared plan is quicker than diagnosing a fault. Because the distribution is an assumption, a sensitivity analysis varied its median from 5 to 30 minutes.

## Experiments

Table 4 lists the evaluations. Each experiment run consisted of 10 minutes of normal operation, the injection of one fault, and 45 minutes of observation.

Table 4. Evaluations and their design

| Evaluation | Hypotheses | Design | Runs |
| --- | --- | --- | --- |
| Detector evaluation | H2, H3 | 5 detectors × 8 faults × 5 seeds, plus 24 h of normal operation | 40 per detector |
| SKAB validation | H4 | Published train–test split, 34 test experiments | 5 detectors |
| E1 fault response | H1, H2, H5 | 8 faults × 3 modes × 20 seeds, paired by seed | 480 |
| M1 sensitivity | H1 | Operator median 5, 10, 20, 30 min × 8 faults × 10 seeds | 320 |
| E4 robustness | H3, H5 | Load surges; a sensor already faulty; 5–20 % message loss | 600 |
| E5 severity | H1, H2, H5 | 8 faults × 3 severity levels × 3 modes × 10 seeds | 720 |
| Live check, E2 load test | H5, H6, H7 | End-to-end check on AWS; 50, 500, 2,000 gateways × 30 min | 1 + 3 |
| E3 cost | H8 | Cost model with measured usage; measured bill | – |

The paired design meant that all modes of the same seed shared the same physical scenario, IT load pattern and operator response time, so differences between modes were caused by the modes and not by chance. Experiment E4 tested robustness in three ways: normal operation with a synchronised load surge in one zone, in which any command is a false remediation; a physical fault while a rack sensor in the same zone had already failed; and the loss of 5, 10 or 20 % of gateway messages. Experiment E5 repeated the fault types at three severity levels to test whether the ranking of the modes depends on how severe a fault is.

## Data

Three kinds of data were used. The main data came from the simulator, which produced telemetry with ground-truth labels for every injected fault. The labels were written to local files only and never entered the cloud pipeline, so the detectors could not see them. The second source was SKAB, a labelled dataset from a real water-pump testbed (Katser & Kozitsin 2020). The third source consisted of measurements of the cloud system itself: timestamps of messages and commands, and the AWS bill.

The data was strictly separated. The detectors were trained on normal operation only, with simulator seeds 101–108, and their thresholds were calibrated on seeds 201–208. The detector evaluation used seeds 11–15 and the experiments seeds 1001–1020. No fault data was used for training. Fault definitions, detector thresholds, playbooks, the operator model, run length and seeds were fixed before the final experiment batch, and the batch was deterministic: repeating it produced identical results.

## Metrics

All physical metrics were computed from the simulator's true state, not from sensor readings, so that no mode was credited for what its own sensors believed. The main metrics were the following:

- **Detected and time to detect (MTTD):** the injected fault was diagnosed with the correct type and target asset; time from fault start to diagnosis.
- **Time to recover (MTTR):** time from fault start until the key value returned to its normal range for good. A value of 0 means that the value never left the normal range, so the fault was contained before it caused harm.
- **Exposure:** the excess of the key value over its limit integrated over time, for example kelvin-minutes above 27 °C.
- **Wrong actions:** commands to equipment for a fault that had not been injected.
- **Alerts:** messages sent to people, including approval requests.
- **Latency:** time from the sensor message to the detector result and to the first command at the gateway.
- **Cost:** monthly AWS cost per hall and per rack.

## Statistical analysis

Recovery times are skewed and partly censored, because some runs do not recover within the observation window. Results were therefore reported as medians with 95 % bootstrap confidence intervals based on 2,000 resamples (Efron & Tibshirani 1993). A run that had not recovered within 45 minutes was counted as 45 minutes, which ranks it below every recovered run.

Modes were compared per fault type with the two-sided Mann–Whitney U test, which compares two distributions without assuming normality (Mann & Whitney 1947). Because eight fault types were tested for each comparison, the p-values were adjusted with the Holm procedure to control the family-wise error rate (Holm 1979). The rank-biserial correlation was reported as the effect size; it ranges from −1 to 1, and a value near 1 means that almost every run of one mode was better than every run of the other. A mode was called better only when the adjusted p-value was below 0.05.

Detection on SKAB was scored with the benchmark's own protocol: pointwise F1 score, false alarm rate and missed alarm rate on the test part of each experiment (Katser & Kozitsin 2020). Latency was summarised with the 50th, 95th and 99th percentiles.

## Tools and environment

The framework and the experiments were written in Python. The simulator and the analysis used NumPy, pandas and matplotlib, the Isolation Forest was trained with scikit-learn (Pedregosa et al. 2011), and the LSTM autoencoder was trained with JAX (Bradbury et al. 2018). The cloud infrastructure was defined with the AWS CDK in Python. During development, the infrastructure ran on LocalStack and the Mosquitto MQTT broker on a cloud virtual machine with four OCPUs (eight hardware threads), and the offline experiments ran on the same machine. Unit tests were written with pytest and executed by GitHub Actions on every change, together with a check that the CDK application synthesises. All code, configuration and results were kept in one Git repository, so that every result can be reproduced from a specific version.
