# Research design and methods

The chapter will describe how the research questions will be answered.

## Design Science Research

The six activities of the DSR methodology of Peffers et al. (2007) will be followed, and the evaluation will be planned with the FEDS framework.

## Requirements and hypotheses

The three gaps will be turned into eight testable hypotheses (H1–H8) on recovery time, detection, false alarms, real-data validity, safety, latency, scalability and cost, each with a pass criterion.

## Operating modes

Three modes will be compared: M1 alert-only with a simulated operator, M2 automation with static thresholds, and M3 automation with machine-learning detection.

## Experiments

Faults will be injected into the simulated hall in paired, repeated runs. The planned experiments are: E1 fault response, E2 load test on AWS, E3 cost, E4 robustness and E5 fault severity.

## Data

Training and test data will come from the simulator with separate seeds. The public Skoltech Anomaly Benchmark (SKAB), recorded from a real pump test rig, will be used for external validation.

## Metrics and statistical analysis

Time to detect, time to recover, detection rate, false alarms, wrong actions, latency and cost will be measured. The modes will be compared with Mann–Whitney U tests with Holm correction and bootstrap confidence intervals.

## Tools and environment

Python, scikit-learn, LocalStack for local development, the AWS CDK and a GitHub repository with automated tests will be used.
