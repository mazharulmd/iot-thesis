# Introduction

This chapter will introduce the topic, the problem and the aim of the thesis, and it will describe how the work will be carried out.

## Background of the thesis

The section will describe data centers as critical infrastructure, the growing power density of GPU racks for artificial intelligence, and the fact that power and cooling failures remain the most common cause of serious outages. It will explain why the response to facility alarms is still largely manual, although the sensor data already exists.

## Problem statement

Data center facility operations lack a validated, cloud-native way to go from IoT sensor data to safe, automatic corrective action within seconds. The section will divide the problem into three gaps: slow manual response, noisy threshold-based detection, and the lack of safety controls for automated actions on physical equipment.

## Purpose, aim and research questions

The purpose is to design, implement and evaluate a serverless AWS framework that detects anomalies in cooling and power telemetry and remediates them automatically. The thesis will answer three research questions:

- **RQ1:** How can a serverless AWS architecture be designed to turn data center IoT telemetry into safe, automated remediation actions?
- **RQ2:** How does machine-learning anomaly detection compare with static thresholds in detection rate, time to detect and false alarms?
- **RQ3:** How much does automated remediation reduce the time to recover compared with alert-only manual response, and at what latency, scalability and cost?

## Scope and delimitations

The cloud system will use real AWS services, while the data hall equipment will be simulated in software with known ground truth. IT-layer remediation, energy optimisation and other cloud providers will be left outside the scope.

## Approach and structure of the thesis

The work will follow Design Science Research. The section will give the structure of the report: theory in Chapters 2–4, research design in Chapter 5, implementation in Chapter 6, results in Chapter 7 and discussion in Chapter 8.
