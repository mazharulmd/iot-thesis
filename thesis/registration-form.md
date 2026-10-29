<!-- Text copy of thesis-topic-proposal.docx (the Word file is the master). Regenerate: pandoc -t gfm --wrap=none thesis/thesis-topic-proposal.docx -o thesis/registration-form.md -->

**Thesis information**

|                                |                                                                                                                  |
|--------------------------------|------------------------------------------------------------------------------------------------------------------|
| **Thesis title in English**    | A Serverless AWS IoT Framework for Automated Anomaly Detection and Remediation in Data Center Infrastructure     |
| **Thesis title in Finnish**    | Palvelimeton AWS IoT -kehys datakeskusinfrastruktuurin poikkeamien automaattiseen havaitsemiseen ja korjaamiseen |
| **Specialization**             | <span class="mark">\[your program’s specialization option\]</span>                                               |
| **Planned start and end date** | <span class="mark">\[1 Sep 2026\]</span> – <span class="mark">\[31 Mar 2027\]</span>                             |
| **Thesis type**                | Research-oriented development work                                                                               |
| **Advising time preference**   | <span class="mark">\[Day / Evening / Any\]</span>                                                                |

**Choice of topic**

The idea came about because of two observations. The Uptime Institute's industry outage surveys indicate that power and cooling failures continue to be a top cause of data center outages, and most facilities still react to them manually. Also, AWS has discontinued the IoT Analytics, IoT Events and Lookout for Equipment services, so there is no existing AWS reference design for this kind of automation.

This topic interests me because it applies cloud and machine learning techniques to a real-world problem: detecting cooling and power faults before they affect data center services. It helps me grow my professional skills by allowing me to use AWS IoT and serverless computing to monitor infrastructure and to understand how automated responses can be implemented safely.

The goal of this thesis is to design, implement and test a serverless AWS-based framework that uses IoT telemetry to detect faults in data center cooling and power systems and executes predefined remediation actions in a simulated environment. High-risk actions will need human approval to proceed, and each action will be checked and reversed if the fault is not cleared.

Research questions:

1\. How can a serverless AWS architecture handle data center IoT telemetry and coordinate safe remediation in a simulated setting?

2\. How do Isolation Forest and an LSTM autoencoder compare with static thresholds in detection rate, detection time and false alarm rate?

3\. Does automated remediation improve recovery time compared with an alert-only approach in controlled fault-injection experiments, and how does the framework perform in terms of end-to-end latency, scalability and AWS cost?

**Thesis methods and implementation**

This development study uses the Design Science Research (DSR) methodology, in which the framework is designed as an artifact and tested through controlled experiments. The work has six parts:

1\. A literature review on data center monitoring, cloud IoT, anomaly detection and self-healing systems.

2\. A simulator of a 20-rack data hall and its main cooling and power equipment: cooling units, pumps, uninterruptible power supplies (UPSs) and power distribution units (PDUs). It will provide IoT telemetry and enable controlled fault injection with known ground truth.

3\. An AWS CDK-defined cloud pipeline that uses AWS IoT Core, AWS Lambda, Amazon DynamoDB, Amazon EventBridge, AWS Step Functions, Amazon SNS and Amazon CloudWatch.

4\. A comparison of static thresholds, Isolation Forest and an LSTM autoencoder. The public SKAB pump dataset (Skoltech Anomaly Benchmark) will be used as an external benchmark. Its results will be reported separately from the simulator results, since the dataset covers only pumps and not the entire data center context.

5\. Remediation playbooks with safety controls such as asset locks, risk tiers, human approval, action verification, rollback, a circuit breaker and rate limits. Remediation will affect the simulator state only; control of real equipment is outside the scope of this thesis.

6\. Fault-injection experiments that compare alert-only response, threshold-based automatic remediation and ML-based automatic remediation across eight fault types and three severity levels. The experiments will measure detection and recovery times, false alarms, end-to-end latency, throughput under load and AWS cost.

The quantitative evaluation is based on eight hypotheses with clear pass criteria, and the criteria for each experiment are set before it is run. Results will be presented as medians with bootstrapped confidence intervals, and planned pairwise comparisons will be made with the Mann–Whitney U test with Holm correction. The data will be obtained from the simulator, the public SKAB dataset and AWS measurements. No human subjects or personal data are involved in the study.

**Relevance of the thesis project**

The project will give me hands-on experience with cloud architecture on AWS, IoT connectivity, infrastructure as code, and event-driven, serverless design. It will also strengthen my skills in machine-learning anomaly detection, safe automation, experimental design, statistical analysis, cloud cost analysis and technical writing, and grow my understanding of data center cooling and power operations.

## Commissioning information

None. The topic is self-initiated, so the commissioning fields are left blank.

**Relevant preparation and experience**

The thesis builds on my previous studies in cloud computing, networking, programming, data analysis and machine learning. It will provide hands-on experience in implementing the AWS IoT pipeline and the simulator, building anomaly-detection models and conducting quantitative fault-injection experiments.
