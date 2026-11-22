# Appendix 1: Work plan and schedule

The work will be carried out in eight steps. The weeks are counted from the approval of the thesis plan.

Table A1. Work plan

| Step | Work | Output | Weeks |
| --- | --- | --- | --- |
| 1 | Foundation: repository, CDK skeleton, LocalStack, simulator and fault injection | Simulated data hall with eight fault types | 1–3 |
| 2 | Telemetry pipeline: gateways, MQTT, topic rule, DynamoDB | Telemetry stored end to end on the local stack | 3–4 |
| 3 | Detection: limits, Isolation Forest, LSTM autoencoder, hybrid rules; SKAB validation | Detector Lambda and evaluation report | 4–7 |
| 4 | Remediation: playbooks in Step Functions, device shadows, notifications | Closed-loop fault correction | 7–9 |
| 5 | Guardrails: locks, approval, recheck, rollback, circuit breaker, rate limit | Tested safety controls | 9–10 |
| 6 | Experiments E1, E4 and E5 in the offline closed loop; statistical analysis | Results tables and figures | 10–13 |
| 7 | Deployment on AWS: live check, load test, cost; live dashboard | Measured latency, scalability and cost | 13–15 |
| 8 | Writing, supervisor feedback, language check, Turnitin, presentation | Final thesis | 1–18, mainly 15–18 |

Table A2. Planned deliverables

| Deliverable | Description |
| --- | --- |
| Source code | Public GitHub repository with the simulator, detectors, playbooks, infrastructure code and tests |
| Infrastructure | Six CDK stacks that can be deployed to and removed from AWS with one command each |
| Experiment data | Run results, statistical tests and figures, reproducible with one command |
| Dashboard | Live control-room view of the hall, incidents and approvals |
| Thesis report | Savonia bachelor's thesis in English |
