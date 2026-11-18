# Anomaly detection and self-healing systems

This chapter covers the two capabilities that the framework combines: detecting that something is wrong, and correcting it automatically and safely. It ends with a review of related work and the research gap that the thesis addresses.

## Faults, errors and anomalies

Dependability research distinguishes between a *fault*, which is the cause of a problem, an *error*, which is the resulting deviation in the system's state, and a *failure*, which is the moment the system no longer delivers its service (Avizienis, Laprie, Randell & Landwehr 2004). In a data center, a worn pump bearing is a fault, the reduced chilled-water flow is an error, and servers shutting down because of overheating are a failure. The purpose of monitoring is to detect errors early enough that a fault can be contained before it becomes a failure.

An *anomaly* is a pattern in data that does not conform to expected normal behaviour (Chandola, Banerjee & Kumar 2009). Anomalies in sensor data can be grouped into three types. *Point anomalies* are single values far from the rest, such as a sudden temperature spike. *Contextual anomalies* are values that are normal in general but not in their context, such as a high fan speed at low IT load. *Collective anomalies* are sequences that are abnormal only as a whole, such as a slow upward drift or a reading that stays perfectly constant. (Chandola et al. 2009.) Facility faults produce all three types, and the slow, collective ones are the hardest to detect with simple limits (Huang et al. 2019).

Not every anomaly is a fault in the equipment. A sensor can itself fail by freezing at one value or by drifting away from the true value. Data-quality faults are important for automation because an automated system acts on what its sensors report: a frozen inlet sensor can hide a rack that is overheating, and a drifting one can trigger unnecessary cooling actions.

## Threshold-based detection

The simplest detector compares each reading with a fixed limit, for example the ASHRAE limit of 27 °C for rack inlet temperature. Threshold rules are transparent, need no training data and are easy for operators to verify, which is why building management systems rely on them. Their limitations are a fixed trade-off between sensitivity and false alarms, blindness to faults that never cross a limit, and the absence of context: a limit cannot tell whether a high current is normal for the present load. (Huang et al. 2019.) Statistical variants, such as alarms based on a number of standard deviations from a mean, adapt to the normal level of each signal but share the other limitations.

## Machine-learning detectors

Most machine-learning methods for anomaly detection in sensor data are *unsupervised* or *semi-supervised*: they learn what normal behaviour looks like from data without labelled faults, and flag deviations from it. This suits facility operations because labelled fault data is rare and every facility is different. (Chandola et al. 2009; Pang, Shen, Cao & van den Hengel 2021.)

**Isolation Forest.** Liu, Ting and Zhou (2008) proposed a detector based on the observation that anomalies are few and different, and are therefore easier to isolate than normal points. The method builds an ensemble of random binary trees, each splitting the data on a randomly chosen feature at a random value. Anomalous points end up in short branches, so the average path length to isolate a point gives its anomaly score. Isolation Forest is fast, needs little memory and has few parameters, which makes it suitable for running inside a serverless function. Its weakness is that it scores each feature vector independently and does not model time unless time-based features are engineered for it.

**LSTM autoencoder.** Long short-term memory (LSTM) networks are recurrent neural networks that learn dependencies in sequences (Hochreiter & Schmidhuber 1997). In an LSTM autoencoder, an encoder compresses a window of multivariate sensor readings into a small latent vector, and a decoder reconstructs the window from it. Trained only on normal data, the network learns to reconstruct normal patterns well, so a high reconstruction error indicates an anomaly. Malhotra et al. (2016) showed that this approach detects anomalies in multi-sensor machine data, including slow degradation that does not appear in any single sensor. Autoencoders have also been applied to industrial and data center cooling systems, where the reconstruction error per sensor helps to locate the faulty component (Holly et al. 2022).

**Hybrid detectors.** Several studies combine learned models with rules derived from physics or expert knowledge. Rules catch hard limit violations and data-quality faults with certainty, while the model catches subtle multivariate changes. (Holly et al. 2022; Vajda et al. 2024.) The framework in this thesis uses such hybrids, because pure models were found to miss certain fault types (Chapter 7).

**Debouncing.** Any detector that scores single time windows produces occasional isolated false alarms. A common remedy is to require several consecutive anomalous windows before an anomaly is confirmed. This trades a short delay for a large reduction in false alarms, and the delay is known in advance.

## Evaluating anomaly detectors

Detector performance is measured by comparing detected anomalies with labelled ones. *Precision* is the share of alarms that are real, *recall* the share of real anomalies that are detected, and the *F1 score* their harmonic mean. Industrial benchmarks also report the *false alarm rate* and the *missed alarm rate*, and for operations the *time to detect* is often as important as accuracy. (Katser & Kozitsin 2020.)

Benchmark results must be interpreted with care. A large comparative study of 71 algorithms found that no single method performs best on all types of time series, and that simple methods are often competitive with deep learning (Schmidl, Wenig & Papenbrock 2022). Wu and Keogh (2023) further argue that many popular benchmarks are flawed, for example because their anomalies are trivial to detect or their labels are inaccurate. The Skoltech Anomaly Benchmark (SKAB) used in this thesis was recorded on a real water-pump testbed with deliberately induced faults and published with a fixed train–test split and a leaderboard (Katser & Kozitsin 2020), which allows the detectors to be compared with published results on real equipment data.

## Self-healing and autonomic computing

The vision of autonomic computing describes systems that manage themselves according to high-level goals. Their self-management covers self-configuration, self-optimisation, self-protection and self-healing, and it is organised as a control loop that *monitors* the system, *analyses* the data, *plans* a response and *executes* it, based on shared *knowledge*. This MAPE-K loop has become the reference model for self-adaptive systems. (Kephart & Chess 2003.)

Self-healing systems detect that they are in a faulty state and return to normal operation without human intervention (Ghosh, Sharman, Rao & Upadhyaya 2007; Psaier & Dustdar 2011). Surveys of self-healing frameworks show that most work targets software: web services, distributed applications, cloud platforms and, more recently, containers and microservices (Schneider, Barker & Dobson 2015; Rouholamini et al. 2024). A recent systematic review of 99 studies on AI-driven self-healing across the edge–cloud continuum reports a shift from observational monitoring towards autonomous repair, but also a validation gap for real deployments (AI-driven self-healing across the edge–cloud continuum 2026). Self-healing has also been studied in smart manufacturing, where fault diagnosis is combined with fault-tolerant control of physical processes (Aldrini, Chihi & Sidhom 2023).

Self-healing usually relies on a set of predefined recovery actions, or *playbooks*, for known failure modes, rather than on actions learned from scratch. This makes the behaviour predictable and auditable. The quality of a self-healing system therefore depends on three things: how quickly and reliably it diagnoses the failure mode, whether the right playbook exists for it, and whether the playbook can be executed safely.

## Safe automation of physical equipment

Automation of physical processes is not all-or-nothing. Parasuraman, Sheridan and Wickens (2000) describe levels of automation for each stage of information processing, from fully manual operation to fully autonomous action, and recommend choosing the level per function according to the consequences of an error. High-risk actions call for a lower level of automation, for example the system proposes an action and a person approves it, while routine, reversible actions can be fully automated. The same idea appears in this thesis as *risk tiers*.

Software engineering offers further patterns that limit the damage automation can do. A *circuit breaker* stops repeated attempts at an operation that keeps failing, so that a fault is not made worse by retries (Nygard 2018). *Rate limits* bound how often an action can be taken, *locks* prevent two automated processes from acting on the same equipment at once, and *idempotent* commands ensure that a repeated message has no additional effect. Site reliability engineering practice adds that every automated action should be observable and reversible, and that automation should escalate to people when its assumptions no longer hold (Beyer, Jones, Petoff & Murphy 2016). Together, these mechanisms are called *guardrails* in this thesis.

## Related work and research gap

Research on anomaly detection in data center facilities has applied statistical methods to physical infrastructure data. Huang et al. (2019) proposed Gaussian models and statistical tests for point anomalies and level shifts in power and cooling data, reducing false alarms compared with fixed thresholds. Ronchieri et al. (2024) studied cooling, electrical and IT metrics in a large scientific data center with z-scores, percentiles and clustering, and Viola et al. (2022) combined log files with monitoring data to find anomaly patterns. Vajda et al. (2024) proposed LSTM-based detection for server farm telemetry with short detection delays, and Holly et al. (2022) used autoencoders with expert-knowledge lookup tables to locate faults in industrial cooling systems. These works detect and sometimes diagnose anomalies, but they end in alarms for people; none of them closes the loop with automatic corrective action.

Research on AI for facility operations focuses on optimising cooling energy during normal operation. Gao (2014) used neural networks to model and improve data center energy efficiency at Google, and Zhan et al. (2025) deployed offline reinforcement learning to control the cooling system of a production data center. These controllers improve efficiency but do not detect and repair faults. In the cloud IoT domain, AWS has published a serverless anomaly detection design based on IoT Core and Lambda, but it ends in notifications (Amazon Web Services 2023). Self-healing research, as described above, mostly targets the software layer.

Table 1 summarises how the closest works relate to the aims of this thesis.

Table 1. Comparison of related work with this thesis

| Work | Target | Detection | Automatic action | Guardrails | Cloud IoT pipeline |
| --- | --- | --- | --- | --- | --- |
| Huang et al. 2019; Ronchieri et al. 2024 | Facility power and cooling | Statistical | No (alarms) | – | No |
| Holly et al. 2022 | Industrial cooling | Autoencoder + expert rules | No (diagnosis) | – | No |
| Zhan et al. 2025 | Data center cooling | Not the focus | Continuous control | Safety constraints | No |
| Amazon Web Services 2023 | Agricultural sensors | Statistical | No (alerts) | – | Yes (serverless) |
| AI-driven self-healing … 2026 | Software, edge–cloud | Machine learning | Yes | Discussed | Partly |
| This thesis | Facility cooling and power | Thresholds vs ML | Remediation playbooks | Approval, verification, rollback, breaker | Yes (serverless) |

No study was found that combines IoT telemetry from data center cooling and power equipment, machine-learning anomaly detection and guarded automatic remediation in a current serverless cloud architecture, and that measures the effect on recovery time, latency and cost. This is the research gap addressed by this thesis. The comparison reflects the literature found during the work and is limited by the databases and search terms used.
