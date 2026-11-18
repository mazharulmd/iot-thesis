---
title: A Serverless AWS IoT Framework for Automated Anomaly Detection and Remediation in Data Center Infrastructure
subtitle: Design and evaluation in a simulated data hall
author: Mazharul Islam Tusar
report_type: THESIS – BACHELOR'S DEGREE
field_of_study: "[Field of study]"
degree_programme: "[Degree programme]"
date: "[Month Year]"
client: None (self-initiated topic)
keywords: data center, Internet of Things, AWS, serverless computing, anomaly detection, machine learning, self-healing systems, automated remediation
---

## Abstract

Power and cooling failures remain a leading cause of costly data center outages, yet most facilities still respond to them manually. The aim of this thesis was to design, implement and evaluate a serverless framework on Amazon Web Services (AWS) that turns IoT telemetry from cooling and power equipment into safe, automatic corrective action.

The work followed Design Science Research. A simulated 20-rack data hall with eight injectable fault types was built, together with an event-driven pipeline of AWS IoT Core, Lambda, EventBridge, Step Functions and DynamoDB defined as infrastructure as code. Static thresholds were compared with Isolation Forest and LSTM autoencoder detectors, and remediation playbooks were protected by locks, risk tiers, human approval, verification, rollback and a circuit breaker. Over 2,000 controlled fault-injection runs compared alert-only response, threshold-based automation and ML-based automation.

Automation reduced the median time to recover from 11–23 minutes to 1–13 minutes, and the hybrid ML detector found all eight fault types, catching slow drifts three to six times earlier than thresholds. No wrong automated action occurred in any run. On real pump data, the ML detector matched thresholds in F1 score but raised more false alarms. [Step 8: add one sentence on the latency and cost measured on real AWS.]
