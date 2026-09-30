# Self-Healing Data Center Facilities: A Serverless AWS IoT Framework for ML-Based Anomaly Detection and Guarded Automated Remediation of Cooling and Power Faults

**Mazharul Islam Tusar** · Master's thesis proposal (two-page version) · September 2026

## Abstract

Power and cooling failures remain the leading cause of costly data center outages, yet most facilities still respond to them by hand: a threshold alarm fires, an engineer investigates, then acts. This delay is dangerous for dense AI racks, where a short cooling loss can force GPUs to throttle or shut down. Self-healing automation is well studied for software services, but not for the physical cooling and power layer observed through IoT sensors. This thesis will design, build and evaluate a serverless framework on Amazon Web Services (AWS) that turns data center IoT telemetry into safe, automatic corrective action. Simulated gateways stream telemetry from a 20-rack data hall through AWS IoT Core; a Lambda detector compares static thresholds with Isolation Forest and LSTM-autoencoder models; and an EventBridge and Step Functions workflow runs remediation playbooks guarded by asset locks, risk tiers, human approval, verification, rollback and a circuit breaker. Following Design Science Research, the framework will be evaluated quantitatively in controlled fault-injection experiments comparing three operating modes (alert-only, threshold automation, ML automation) across eight fault types, validated on the real SKAB pump dataset, and measured on real AWS for latency, scalability and cost. Eight pre-registered hypotheses define success. Pilot results from the prototype (1,400 simulated runs) show median time to recover falling from 11–23 min to 1–13 min with no wrong actions. The expected outcome is an open-source reference architecture, a reusable guardrail pattern for automating physical equipment, and measured evidence of where ML detection helps and where it does not.

## 1. Introduction and Problem Statement

Outages are becoming rarer but more expensive: 57 % of operators report that their latest major outage cost over $100,000, and power and cooling faults (UPS, transfer switches, chillers) are still the main cause (Uptime Institute, 2026). Facilities already collect sensor data through BMS and DCIM systems, but act on it manually. Cloud IoT and serverless services can react in seconds and cost little when nothing is wrong, yet AWS has retired IoT Analytics, IoT Events and Lookout for Equipment since 2025, leaving no current reference design.

**Problem.** Data center facility operations lack a validated, cloud-native way to go from IoT sensor data to safe, automatic corrective action within seconds. Three gaps drive this: (1) *slow, manual response*, since recovery time depends on staffing; (2) *noisy detection*, since static limits miss slow drifts such as pump wear and false-alarm on load swings; and (3) *unsafe automation*, since actions on physical equipment can make faults worse without approval, verification and rollback.

## 2. Research Questions, Objectives and Hypotheses

- **RQ1:** How can a serverless AWS architecture turn data center IoT telemetry into safe, automated remediation?
- **RQ2:** How does ML anomaly detection compare with static thresholds in detection rate, time to detect (MTTD) and false alarms?
- **RQ3:** How much does automated remediation reduce time to recover (MTTR) versus alert-only response, and at what latency, scale and cost?

**SMART objectives (6 months).** O1 (month 1): review literature and fix eight hypotheses with numeric pass criteria. O2 (month 2): build a 20-rack simulated hall with 8 injectable fault types. O3 (months 2–4): deploy the pipeline as five AWS CDK stacks with ≥ 100 automated tests. O4 (month 4): implement playbooks with six guardrails. O5 (months 5–6): run ≥ 1,400 fault runs plus AWS load and cost tests, and judge every hypothesis.

| # | Hypothesis | Pass criterion |
| --- | --- | --- |
| H1 | Automation shortens recovery | MTTR M2 < M1 for every limit-detectable harmful fault (Holm p < 0.05) |
| H2 | ML detects more faults, slow ones earlier | M3 detects all 8 fault types; lower MTTR for slow-developing faults |
| H3 | ML adds no false actions | 0 automated false actions; ≤ 2 notify-only alerts per hall per day |
| H4 | Detection generalises to real data | SKAB F1 ≥ thresholds and within 0.05 of best published (0.78) |
| H5 | Guardrails keep automation safe | 0 wrong actions in all runs; every guardrail covered by a test |
| H6–H8 | Fast, scalable, affordable on real AWS | p95 message-to-command ≤ 5 s; ≥ 99.9 % processed at 2,000 gateways; ≤ $1 per rack per month |

## 3. Literature Review

**Self-healing systems.** Autonomic computing frames self-healing as a monitor–analyse–plan–execute (MAPE-K) loop (Kephart & Chess, 2003). A recent systematic review finds such loops mature for containers, VMs and microservices across the edge–cloud continuum, and stresses governed remediation with guardrails and rollback ("AI-driven self-healing," 2026). These works target software, not physical plant.

**AI for facilities.** Facility AI concentrates on optimising cooling energy in normal operation, e.g. offline reinforcement learning in a production data center (Zhan et al., 2025) and simulator-based RL at Meta (Meta Engineering, 2024). These controllers improve normal operation rather than detecting and repairing faults.

**Anomaly detection debate.** Unsupervised detectors such as Isolation Forest (Liu et al., 2008) and LSTM autoencoders (Malhotra et al., 2016) catch drifts that fixed limits miss, but on the SKAB benchmark they do not beat simple limits on F1 and often raise more false alarms (Katser & Kozitsin, 2020). Whether ML justifies its complexity for facilities is therefore open.

**Cloud IoT.** AWS reference designs for serverless IoT anomaly detection (AWS, 2023) and the managed multivariate detection added to AWS IoT SiteWise (AWS, 2025) stop at alerts, not actions.

**Gap.** No work found combines facility cooling and power telemetry, ML detection and guarded automatic remediation in a current serverless architecture with measured recovery time, latency and cost.

## 4. Methodology

**Design.** Quantitative Design Science Research (Hevner et al., 2004; Peffers et al., 2007): the framework is the artefact, evaluated *ex post* in an artificial setting (Venable et al., 2016), since injecting faults into live plant is unsafe and a simulator gives exact ground truth.

**Artefact.** A Python simulator models one hall (4 zones, 20 GPU racks, N+1 CRAH units, duty/standby pumps, 2 UPS, 4 PDUs) with a lumped energy balance; five gateways publish batched MQTT telemetry every 10 s. The AWS pipeline uses IoT Core, Lambda, EventBridge, Step Functions, DynamoDB and SNS, defined in AWS CDK and mirrored on LocalStack for development.

**Data collection.** (1) Controlled experiments: 8 fault types (CRAH fan failure, rack hotspot, chilled-water drift, pump degradation, stuck and drifting sensors, UPS battery overheating, PDU overload) × 3 modes (M1 alert-only with a simulated human, M2 thresholds + automation, M3 ML + automation) × 20 paired seeds, plus robustness runs (load surges, faulty sensors, 5–20 % message loss) and human-delay sensitivity (5–30 min). (2) SKAB real pump data with its published split. (3) Real AWS in ap-south-1: end-to-end timestamps, load tests at 50 / 500 / 2,000 gateways, and the Cost Explorer bill. Detectors train on normal data only, with disjoint seeds for training, calibration and testing; all settings are frozen before final runs.

**Analysis.** Medians with 95 % bootstrap CIs; two-sided Mann–Whitney U tests per fault, Holm-corrected, with rank-biserial effect sizes (M1 vs M2 isolates automation, M2 vs M3 isolates ML); runs unrecovered at 45 min are censored. Detection uses F1, false- and missed-alarm rates; latency uses p50/p95/p99; cost uses a usage-based model checked against the measured bill.

## 5. Significance and Contribution

The thesis moves self-healing from the IT layer to the facility layer. It will contribute (1) an open-source, one-command-deployable serverless reference architecture built only on actively supported AWS services; (2) a reusable guardrail pattern (locks, risk tiers, one-time approval links, recheck, verification, rollback, circuit breaker, rate limit) for automating physical equipment; (3) pre-registered, statistically tested evidence on recovery time, latency, scale and cost that operators can benchmark against; and (4) an honest account of where ML helps (early detection of slow drifts) and where simple limits suffice.

## References

- *AI-driven self-healing across the edge–cloud continuum: A systematic literature review.* (2026). *Information and Software Technology*. https://www.sciencedirect.com/science/article/pii/S0950584926002211
- AWS. (2023). *Streamlining agriculture operations with serverless anomaly detection using AWS IoT*. AWS IoT Blog. https://aws.amazon.com/blogs/iot/serverless-iot-anomaly-detection/
- AWS. (2025). *AWS IoT SiteWise introduces multivariate anomaly detection*. https://aws.amazon.com/about-aws/whats-new/2025/07/aws-iot-sitewise-multivariate-anomaly-detection/
- Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. *MIS Quarterly, 28*(1), 75–105.
- Katser, I. D., & Kozitsin, V. O. (2020). *Skoltech Anomaly Benchmark (SKAB)*. https://github.com/waico/SKAB
- Kephart, J. O., & Chess, D. M. (2003). The vision of autonomic computing. *Computer, 36*(1), 41–50.
- Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2008). Isolation forest. In *Proc. IEEE ICDM* (pp. 413–422).
- Malhotra, P., Ramakrishnan, A., Anand, G., Vig, L., Agarwal, P., & Shroff, G. (2016). *LSTM-based encoder-decoder for multi-sensor anomaly detection*. arXiv:1607.00148.
- Meta Engineering. (2024). *Simulator-based reinforcement learning for data center cooling optimization*. https://engineering.fb.com/2024/09/10/data-center-engineering/simulator-based-reinforcement-learning-for-data-center-cooling-optimization/
- Peffers, K., Tuunanen, T., Rothenberger, M. A., & Chatterjee, S. (2007). A design science research methodology for information systems research. *Journal of Management Information Systems, 24*(3), 45–77.
- Uptime Institute. (2026). *Annual outage analysis 2026*. https://intelligence.uptimeinstitute.com/resource/annual-outage-analysis-2026
- Venable, J., Pries-Heje, J., & Baskerville, R. (2016). FEDS: A framework for evaluation in design science research. *European Journal of Information Systems, 25*(1), 77–89.
- Zhan, X., et al. (2025). *Data center cooling system optimization using offline reinforcement learning*. arXiv:2501.15085.
