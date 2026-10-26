<!-- Generated from thesis-topic-proposal.docx (the submitted version); edit the .docx, then re-run: pandoc -t gfm thesis/thesis-topic-proposal.docx -o thesis/registration-form.md -->

## Thesis information

|                                |                                                                                                                  |
|--------------------------------|------------------------------------------------------------------------------------------------------------------|
| **Thesis title in English**    | A Serverless AWS IoT Framework for Automated Anomaly Detection and Remediation in Data Center Infrastructure     |
| **Thesis title in Finnish**    | Palvelimeton AWS IoT -kehys datakeskusinfrastruktuurin poikkeamien automaattiseen havaitsemiseen ja korjaamiseen |
| **Specialization**             | <span class="mark">\[your program’s specialization option\]</span>                                               |
| **Planned start and end date** | <span class="mark">\[1 Sep 2026\]</span> – <span class="mark">\[31 Mar 2027\]</span>                             |
| **Thesis type**                | Research-oriented development work                                                                               |
| **Advising time preference**   | <span class="mark">\[Day / Evening / Any\]</span>                                                                |

## Choice of topic

The topic is self-initiated, and the thesis has no commissioner. Potential commissioners include data center operators, colocation providers, and cloud consultancies that monitor facility infrastructure. The topic arose from two observations. Industry outage surveys by the Uptime Institute show that power and cooling failures remain a leading cause of costly data center outages, yet most facilities still respond to them manually. In addition, AWS has retired IoT Analytics, IoT Events, and Lookout for Equipment, which leaves no current AWS reference design for this type of automation.

This topic interests me because it applies cloud and machine-learning methods to a practical problem: detecting cooling and power faults before they disrupt data center services. It supports my professional development because it lets me apply AWS IoT and serverless computing to infrastructure monitoring and study how automated responses can be made safe.

The aim of this thesis is to design, implement, and evaluate a serverless AWS framework that uses IoT telemetry to detect faults in data center cooling and power systems and to execute predefined remediation actions in a simulated environment. High-risk actions will require human approval, and every action will be verified and rolled back if it does not resolve the fault.

Research questions:

\(1\) How can a serverless AWS architecture process data center IoT telemetry and coordinate safe remediation in a simulated environment?

\(2\) How do Isolation Forest and an LSTM autoencoder compare with static thresholds in detection rate, detection time, and false-alarm rate?

\(3\) How does automated remediation affect recovery time compared with an alert-only response in controlled fault-injection experiments, and how does the framework perform in terms of end-to-end latency, scalability, and AWS cost?

## Thesis methods and implementation

This research-oriented development study will follow the Design Science Research methodology, in which the framework is built as an artifact and evaluated through controlled experiments. The work consists of six parts:

\(1\) A literature review of data center monitoring, cloud IoT, anomaly detection, and self-healing systems.

\(2\) A simulator of a 20-rack data hall and its main cooling and power assets: cooling units, pumps, uninterruptible power supplies (UPSs), and power distribution units (PDUs). It will publish IoT telemetry and support controlled fault injection with known ground truth.

\(3\) A cloud pipeline defined as infrastructure as code with the AWS CDK, using AWS IoT Core, AWS Lambda, Amazon DynamoDB, Amazon EventBridge, AWS Step Functions, Amazon SNS, and Amazon CloudWatch.

\(4\) A comparison of static thresholds, Isolation Forest, and an LSTM autoencoder. The public SKAB pump dataset (Skoltech Anomaly Benchmark) will serve as an external benchmark. Its results will be reported apart from the simulator results because it covers pumps only, not the full data center context.

\(5\) Remediation playbooks with safety controls, including asset locks, risk tiers, human approval, action verification, rollback, a circuit breaker, and rate limits. Remediation will change simulator state only; control of physical equipment is outside the scope of this thesis.

\(6\) Fault-injection experiments comparing an alert-only response with threshold-based and ML-based automated remediation across eight fault types and three severity levels. The experiments will measure detection and recovery times, false alarms, end-to-end latency, throughput under load, and AWS cost.

The quantitative evaluation is structured around eight hypotheses with explicit pass criteria; the criteria for each experiment are fixed before it is run. Results will be summarized as medians with bootstrap confidence intervals, and planned pairwise comparisons will use Mann–Whitney U tests with Holm correction. Data will come from the simulator, the public SKAB dataset, and AWS measurements. The study involves no human participants or personal data.

Preliminary schedule: Sep–Oct 2026, literature review, prototype, and offline experiments; Nov 2026, severity sweep and validation on AWS; Dec 2026–Feb 2027, writing; Mar 2027, final revisions, seminar, and maturity test. Code, data, and results will be maintained in a GitHub repository.

## Relevance of the thesis project

The project will develop my practical skills in AWS cloud architecture, IoT connectivity (MQTT, X.509 certificates, and device shadows), infrastructure as code, and serverless, event-driven design. It will also strengthen my skills in machine-learning anomaly detection, safe automation, experimental design, statistical analysis, cloud cost analysis, and technical writing, and build my knowledge of data center cooling and power operations.

## Commissioning information

None. The topic is self-initiated, so the commissioning fields are left blank.

## Relevant preparation and experience

The thesis builds on my prior studies in cloud computing, networking, programming, data analysis, and machine learning. It will add practical project experience through implementing the AWS IoT pipeline and the simulator, developing anomaly-detection models, and running quantitative fault-injection experiments.
