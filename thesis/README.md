# Thesis: sources, evidence and remaining work

**A Serverless AWS IoT Framework for Automated Anomaly Detection and Remediation in Data Center
Infrastructure** (Master's thesis, Mazharul Islam Tusar).

| File | What it is |
| --- | --- |
| [proposal.md](proposal.md) | The approved research proposal (text, diffable) |
| [proposal.pdf](proposal.pdf) · [proposal.docx](proposal.docx) | The same proposal as PDF and Word |
| [proposal-2page.md](proposal-2page.md) · [proposal-2page.pdf](proposal-2page.pdf) | Two-page version of the proposal (title, abstract, problem, RQs/objectives/hypotheses, literature, method, significance, references) |
| [methodology.md](methodology.md) | Methodology and evaluation criteria: DSR design, hypotheses H1–H8 with pass criteria, protocol, validity (also a live doc in Claude) |
| This file | Where each research question and chapter gets its evidence, what changed since the proposal, and what is left |

The proposal and the methodology are also kept as live documents in Claude; edits there are
re-exported into this folder, so this repository is the single source for the whole thesis.

## Keeping everything in GitHub

- **Code, docs and thesis files** are committed to `main` as each step is built.
- **On the server**, start every session with `git pull`, and after a run commit the results with
  `scripts/git-publish.sh "what was run"` (it checks for secrets, pulls, then pushes).
- **Never committed:** `.env`, `certs/`, LocalStack data, simulator run folders and the SKAB download
  (see `.gitignore`).

## Progress

| Step | Content | Status |
| --- | --- | --- |
| 1 | CDK project, foundation stack, LocalStack + Mosquitto server setup | Done |
| 2 | Data hall simulator and fault injector | Done |
| 3 | Live telemetry pipeline (gateways → MQTT → rule → DynamoDB → detector) | Done |
| 4 | Detection: D0 limits, D1 Isolation Forest, D2 LSTM autoencoder, hybrids; SKAB validation | Done |
| 5 | Remediation: playbooks, one generic state machine, device-shadow commands, verification, rollback | Done |
| 6 | Guardrails: risk tiers, approval with one-time links, recheck, circuit breaker, rate limit | Done |
| 7 | Experiments E1, M1 sensitivity, E4 (1,400 runs on the OCI server) | Done |
| 8 | Real AWS in ap-south-1: end-to-end check, E2 load test, E3 cost | Built; to run ([docs/aws.md](../docs/aws.md)) |
| 9 | Thesis writing, figures, supervisor review | To do |

## Research questions → evidence

| RQ | Evidence in this repository |
| --- | --- |
| **RQ1** How can a serverless AWS architecture turn IoT telemetry into safe, automated remediation? | Architecture as code in `infra/stacks/` (Foundation, Data, Detection, Remediation, Iot); design notes in [docs/pipeline.md](../docs/pipeline.md), [docs/remediation.md](../docs/remediation.md), [docs/guardrails.md](../docs/guardrails.md); end-to-end checks `tools/e2e_check.py`, `tools/e2e_approval.py` (LocalStack, then real AWS) |
| **RQ2** ML vs static thresholds: accuracy and time to detect | [docs/detection.md](../docs/detection.md); `detection/results/offline_summary.md`, `skab_summary.md`; E1 detection rate and MTTD in `experiments/results/e1_summary.md` (M2 vs M3) |
| **RQ3** Recovery time vs alert-only response, latency, scalability, cost | E1 and M1 sensitivity in [docs/experiments.md](../docs/experiments.md) and `experiments/results/`; latency `tools/latency.py`; E2 `experiments/results/e2_summary.md`; E3 `e3_cost.md`, `e3_measured.md` (after Step 8) |

## Chapter plan → material

| Chapter (proposal §12) | Material to draw on |
| --- | --- |
| 1 Introduction | Proposal §1–3, §5 |
| 2 Background and literature | Proposal §4 and References; SKAB leaderboard in `detection/results/skab_summary.md` |
| 3 Requirements and design | Proposal §6.2, §6.6, §7.2–7.6; [docs/pipeline.md](../docs/pipeline.md), [docs/remediation.md](../docs/remediation.md), [docs/guardrails.md](../docs/guardrails.md); playbook catalog `playbooks/catalog.py` |
| 4 Implementation | [docs/simulator.md](../docs/simulator.md), [docs/detection.md](../docs/detection.md), `infra/`, `lambdas/`, `simulator/`, `detection/`; tests in `tests/` (121 unit tests, CI in `.github/workflows/ci.yml`) |
| 5 Experimental setup | [docs/experiments.md](../docs/experiments.md) (design, metrics, statistics, simulated human); [docs/aws.md](../docs/aws.md) (E2, E3) |
| 6 Results | `experiments/results/*.md` and `fig_*.png`; `detection/results/`; Step 8 outputs |
| 7 Discussion | Threats to validity in [docs/experiments.md](../docs/experiments.md); deviations below; LocalStack vs AWS differences |
| 8 Conclusions and future work | Proposal §8 and §12 (real BMS pilot, Greengrass edge fallback, LLM-assisted diagnosis) |

## Deviations from the proposal (to state in the thesis)

| Proposal | Built | Reason |
| --- | --- | --- |
| D2 trained in PyTorch, exported to ONNX, run in a Lambda container image | LSTM autoencoder trained with JAX; D1 and D2 run in plain NumPy inside a zip Lambda (`detection/models.py`) | No container image or ONNX Runtime needed; smaller package, faster cold start |
| D0, D1, D2 | Also hybrids D1h/D2h (ML + limits + flatline rule); **D2h is deployed** | Pure ML missed hard limit breaches and stuck sensors; hybrids keep ML's early warning without losing them |
| 7 fault types, 420 E1 runs | 8 fault types (sensor fault split into stuck and drifting), 480 E1 runs | Stuck and drifting sensors behave differently for detection |
| One state machine per playbook | One generic state machine; playbooks are data (`playbooks/catalog.py`) | One definition to test and deploy; new playbooks need no infrastructure change |
| AWS IoT Device SDK for gateways | paho-mqtt (MQTT 3.1.1 over TLS with X.509 on AWS) | Same code path against Mosquitto locally and IoT Core on AWS |
| Main experiments on AWS | Main experiments offline/LocalStack; real AWS for final validation, E2 and E3 | Cost control and repeatability; AWS confirms that results carry over |
| Region `eu-north-1` or `us-east-1` | `ap-south-1` (Mumbai) | Chosen for the author's location; every service used is available there |
| E2 at 50/500/2,000/10,000 devices | 50/500/2,000 measured, 10,000 extrapolated | Budget; the extrapolation states the Lambda concurrency required |
| Grafana dashboards | CloudWatch metrics and logs plus the command-line status tools in `tools/` | Fewer moving parts; figures come from `experiments/analysis.py` |

## Reproducing the results

```bash
make test                 # unit tests
make experiments          # E1, M1 sensitivity, E4 (offline, ~50 min on 7 workers) -> experiments/results/
make analysis             # tables, statistical tests, figures from runs.csv
make aws-deploy && make aws-check && make aws-loadtest && make aws-cost && make aws-destroy   # Step 8
```

The SKAB dataset (GPL-3.0) is downloaded on first use into `detection/data/` and is not stored in
this repository.
