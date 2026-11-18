# Introduction

Data centers have become part of the critical infrastructure of society. Payment systems, public services, hospitals and the rapidly growing workloads of artificial intelligence all depend on facilities that must run without interruption. The servers in these facilities in turn depend on physical equipment: cooling units, chilled-water pumps and chillers that remove heat, and uninterruptible power supplies (UPS) and power distribution units (PDU) that keep electricity flowing. When one of these devices fails or slowly degrades, the IT equipment it supports is at risk within minutes.

Industry surveys show that outages are becoming less frequent but more expensive, and that power and cooling failures remain their most common cause. At the same time, rack power densities are rising sharply because of graphics processing unit (GPU) clusters used for machine learning. A dense GPU rack can draw more than 40 kW, and a short loss of cooling can force its processors to slow down or shut down. The margin for a slow human response is therefore shrinking.

Most facilities already collect sensor data from their equipment through building management systems (BMS) or data center infrastructure management (DCIM) tools. The response to that data, however, is still largely manual. A fixed alarm limit is crossed, an operator is notified, the operator investigates, and only then is corrective action taken. The time this takes depends on staffing, on the time of day and on how clearly the alarm points to its cause. Slowly developing faults, such as a pump that is wearing out, may not cross any alarm limit until the damage is already done.

In software operations, the idea of *self-healing* systems is well established: systems that detect, diagnose and correct their own faults without waiting for a person. Cloud services have also made it practical to process sensor data in real time with *serverless* computing, in which code runs only when an event occurs and is billed only for that time. Combining these two ideas for the physical facility layer of a data center, rather than for the software running in it, has received much less attention. The topic is also timely for practical reasons: Amazon Web Services (AWS) retired several of its managed IoT analytics services in 2025 and 2026, which leaves no current reference design for this kind of automation on AWS.

The topic was chosen by the author and the thesis has no commissioning organisation. It is nevertheless closely tied to working life. Data center operators, facility engineers and cloud engineers need practical, affordable and well-tested designs for automating operations, and they need evidence of what such automation can and cannot do safely. For the author, the topic combines cloud architecture, the Internet of Things (IoT), machine learning and statistics, which are central to the author's professional development.

## Purpose, aim and research questions

The purpose of this thesis is to design, implement and evaluate a serverless framework on AWS that uses IoT telemetry to detect anomalies in data center cooling and power equipment and to remediate them automatically. The output of the thesis is a working, open-source framework defined as infrastructure as code, a simulated data hall for testing it, and a set of controlled experiments that measure its effect.

The aim of the thesis is to show whether, and under which conditions, guarded automation can shorten the recovery from facility faults without causing unsafe actions, and to give operators a reusable design and measured evidence on which to base their own decisions.

The thesis answers three research questions:

- **RQ1:** How can a serverless AWS architecture be designed to turn data center IoT telemetry into safe, automated remediation actions?
- **RQ2:** How does machine-learning anomaly detection compare with static thresholds in detection rate, time to detect and false alarms for typical cooling and power faults?
- **RQ3:** How much does automated remediation reduce the time to recover compared with alert-only manual response, and at what end-to-end latency, scalability and cost?

## Scope and delimitations

The cloud system is built on real AWS services, but the data center equipment it monitors and controls is simulated in software. The simulated hall has 20 GPU racks, five cooling units, two pumps, a chiller, two UPS units and four PDUs, and eight fault types can be injected into it with known ground truth. Remediation commands change only the state of the simulator; controlling real equipment or connecting to a real building management system is outside the scope of this thesis.

The thesis is also limited to the facility layer. IT-layer remediation, such as restarting virtual machines or containers, is not studied, and neither is continuous energy optimisation of cooling, which is a separate research field. Only AWS is used; portability to other cloud providers is discussed but not implemented. The detection models are deliberately lightweight, because they must run inside a serverless function, and the thesis does not aim to develop new machine-learning methods.

## Approach and structure

The work follows Design Science Research, in which a purpose-built artefact is designed, demonstrated and evaluated against requirements derived from a practical problem. The evaluation is quantitative: faults are injected into the simulated hall, and three operating modes are compared in repeated, paired experiments. The detectors are additionally validated on a public dataset recorded from a real pump testbed.

Chapters 2–4 form the theoretical framework: data center facility operations, cloud IoT and serverless computing, and anomaly detection and self-healing systems. Chapter 5 describes the research design and methods, Chapter 6 the implementation, and Chapter 7 the results. Chapter 8 answers the research questions, discusses the reliability and ethics of the work, and reviews the thesis process.
