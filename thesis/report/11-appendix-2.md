# Appendix 2: Source code and reproduction of the results

All source code, infrastructure definitions, experiment scripts and result files of this thesis are published in the Git repository https://github.com/mazharulmd/iot-thesis. The repository is organised as follows.

| Folder | Contents |
| --- | --- |
| `infra/` | AWS CDK application and its six stacks |
| `simulator/` | Data hall model, fault injector, scenario files, live MQTT gateways |
| `bridge/` | Local stand-in for IoT Core rules and device shadows |
| `detection/` | Features, detectors D0–D2h, diagnosis rules, training, evaluation, SKAB validation |
| `lambdas/` | Detector, remediation and approval functions |
| `playbooks/` | Playbook catalogue, state machine definition, interpreter for the offline loop |
| `experiments/` | Offline closed loop, metrics, experiment batches, statistical analysis, cost model |
| `tools/` | Status, latency, end-to-end checks, load generator, cost report |
| `tests/` | Unit tests |

The results in Chapter 7 can be reproduced with the following commands on a Linux machine with Python 3.11 or newer:

| Command | Result |
| --- | --- |
| `make venv` | Creates the Python environment and installs the dependencies |
| `make test` | Runs the unit tests |
| `make train` and `make evaluate` | Trains the detectors and repeats the detector evaluation (Table 11) |
| `make skab` | Downloads SKAB and repeats the validation (Table 12) |
| `make playbook-eval` | Repeats the closed-loop playbook test (Section 7.3) |
| `make experiments` | Runs E1, the M1 sensitivity, E4 and E5 offline |
| `make analysis` | Produces the result tables, statistical tests and figures |
| `make aws-cost` | Produces the cost model (Table 18) |
| `make aws-deploy`, `make aws-check`, `make aws-loadtest`, `make aws-destroy` | Deploys the framework to AWS, runs the end-to-end check and the load test, and removes everything |

The experiments are deterministic: the same seeds produce the same results. The SKAB dataset is downloaded from its public source on first use and is not stored in the repository.
