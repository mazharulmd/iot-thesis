---
title: A serverless AWS IoT framework for automated anomaly detection and remediation in data center infrastructure
subtitle: thesis plan
author: Mazharul Islam Tusar
report_type: THESIS PLAN – BACHELOR'S DEGREE
field_of_study: Technology, Communication and Transport
degree_programme: "[Degree Programme in …]"
date: "[Month Day, Year]"
client: None (self-initiated topic)
keywords: data center, Internet of Things, AWS, serverless computing, anomaly detection, machine learning, self-healing systems, automated remediation
---

## Abstract

Power and cooling failures are a leading cause of costly data center outages, yet most facilities still respond to them manually. The aim of the planned thesis is to design, implement and evaluate a serverless framework on Amazon Web Services (AWS) that detects anomalies in IoT telemetry from cooling and power equipment and corrects them automatically and safely.

Design Science Research will be used. A simulated data hall with injectable faults and an event-driven AWS pipeline will be built with AWS IoT Core, Lambda, EventBridge, Step Functions and DynamoDB, defined as infrastructure as code. Static thresholds will be compared with machine-learning detectors, and remediation playbooks will be protected by locks, human approval, verification and rollback. Alert-only response, threshold-based automation and machine-learning-based automation will be compared in repeated fault-injection experiments, and the detectors will be validated on a public dataset from real equipment. Latency, scalability and cost will be measured on AWS.

The expected result is an open-source, reproducible framework and measured evidence of how much guarded automation can shorten recovery from facility faults, and where human approval remains necessary.
