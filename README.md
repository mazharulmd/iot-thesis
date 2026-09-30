# dc-selfheal

A serverless AWS IoT framework for automated anomaly detection and remediation in data center infrastructure (Master's thesis project).

## Repository layout

| Folder | Contents | Built in |
| --- | --- | --- |
| `infra/` | AWS CDK app and stacks | Step 1 onwards |
| `simulator/` | Data hall model, fault injector, live MQTT gateways | Steps 2–3 |
| `bridge/` | Local stand-in for IoT rules + device shadows | Step 3 |
| `common/` | Topology, topics, AWS helpers | Step 3 |
| `tools/` | Status, commands, incidents, latency probe, end-to-end check | Steps 3–5 |
| `detection/` | Features, detectors (D0/D1/D2/hybrids), diagnosis, training, evaluation, SKAB | Step 4 |
| `lambdas/` | Detector (Step 4), remediation steps (Step 5), approval page (Step 6) | Steps 4–6 |
| `playbooks/` | Playbook catalog (data), state machine definition, small ASL runner | Step 5 |
| `experiments/` | Offline closed loop, metrics, experiment batches (E1, E4), analysis and figures; load tests later | Steps 5–8 |
| `tests/` | Unit tests | All steps |
| `docs/` | Diagrams and runbook | All steps |
| `thesis/` | Research proposal, RQ → evidence map, deviations, remaining work | – |

## Two ways to run

- **Local (development and main experiments):** LocalStack + Mosquitto on an Ubuntu server. See [docs/local-setup.md](docs/local-setup.md).
- **Offline closed loop (no AWS at all):** simulator, detector and playbooks in one process, e.g. `make playbook S=crah_fan_failure`.

- **Real AWS (final validation, load test, cost):** the same CDK code plus an IoT Core stack, deployed with `make aws-deploy`; see [docs/aws.md](docs/aws.md).

Step guides: [simulator](docs/simulator.md) · [pipeline](docs/pipeline.md) · [detection](docs/detection.md) · [remediation](docs/remediation.md) · [guardrails](docs/guardrails.md) · [experiments](docs/experiments.md) · [real AWS](docs/aws.md)

**Thesis:** the research proposal (Markdown, PDF, Word) and a map from each research question and chapter to its evidence are in [thesis/](thesis/README.md).

## Real AWS in short

Prerequisites on the server: the AWS CLI v2, Node.js 22 and the CDK CLI (installed by
`scripts/setup-server.sh`), and an AWS CLI profile for your account (default name `thesis`).

```bash
make aws-whoami && make aws-bootstrap && make aws-deploy   # deploy (confirm the SNS email)
make aws-devices && make aws-check                         # certificate, end-to-end checks
make aws-loadtest && make aws-cost                         # E2 load test, E3 cost model
make aws-destroy                                           # remove everything: charges stop
```

The full runbook, costs and troubleshooting are in [docs/aws.md](docs/aws.md).
