---
title: A serverless AWS IoT framework for automated anomaly detection and remediation in data center infrastructure
subtitle: design and evaluation in a simulated data hall
author: Mazharul Islam Tusar
report_type: THESIS – BACHELOR'S DEGREE
field_of_study: Technology, Communication and Transport
degree_programme: "[Degree Programme in …]"
date: "[Month Day, Year, e.g. March 31, 2027]"
client: None (self-initiated topic)
keywords: data center, Internet of Things, AWS, serverless computing, anomaly detection, machine learning, self-healing systems, automated remediation
---

## Abstract

Power and cooling failures are a leading cause of costly data center outages, yet most facilities still respond to them manually. The aim was to design, implement and evaluate a serverless framework on Amazon Web Services (AWS) that detects anomalies in IoT telemetry and corrects them automatically and safely.

Design Science Research was used. A simulated data hall with eight fault types and an event-driven AWS pipeline were built. Static thresholds were compared with Isolation Forest and LSTM autoencoder detectors, and the remediation playbooks were protected by locks, human approval, verification and rollback. Alert-only response, threshold-based automation and machine-learning-based automation were compared in 2,120 fault-injection runs, and the detectors were tested on real pump data.

The median time to recover was reduced from 11–23 to 1–13 minutes by automation. All eight fault types were detected by the machine-learning detector, slowly developing faults three to six times earlier than with static thresholds, and no incorrect automated action was observed. On real pump data, the F1 score of the machine-learning detector equalled that of static thresholds, but more false alarms were raised. On AWS, 2,000 gateways were served within 0.1 seconds (95th percentile) without message loss, at [Step 8: cost] per rack per month. Guarded automation shortens recovery, whereas high-risk faults remain dependent on human approval.
