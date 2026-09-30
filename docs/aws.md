# Real AWS (Step 8): validation, load test (E2) and cost (E3)

The same code that ran on LocalStack is deployed to your AWS account in **ap-south-1 (Mumbai)**.
There is no bridge on AWS: the gateways connect to **IoT Core** with an X.509 certificate, a topic
rule stores telemetry and invokes the detector, and playbooks command the equipment through IoT
Core device shadows.

```
simulator / load generator (OCI server) --MQTT over TLS 8883--> IoT Core
    topic rule --> DynamoDB Telemetry + detector Lambda --> EventBridge --> Step Functions playbooks
    remediation Lambda --UpdateThingShadow--> IoT Core --shadow delta--> gateway
```

Plan the AWS work for **one day** and destroy everything at the end of it (`make aws-destroy`).

## Cost and safety first

| Activity | Estimated cost (list price, before credits) |
| --- | --- |
| Deploy + `make aws-check` | a few cents |
| `make aws-loadtest` (50, 500, 2,000 gateways, 30 min each) | about $2–3 |
| Everything left running for a month by mistake | a few dollars (on-demand tables, idle), so still destroy it |

1. In the Billing console, create a **budget** (e.g. $10 per month) with an email alert.
2. Estimates use list prices in `experiments/prices.yaml`; check them for ap-south-1 in the
   [AWS Pricing Calculator](https://calculator.aws/). The load test prints its estimate and asks
   before it starts.

## One-time setup on the server

**Credentials.** The `aws-*` targets use the named profile in `AWS_THESIS_PROFILE` (default
`thesis`) and ignore LocalStack's dummy keys in `.env`. Either:

- *IAM user (simplest):* in the IAM console create a user `thesis-cli` with the
  `AdministratorAccess` policy and an access key for the CLI, then on the server
  `aws configure --profile thesis` (region `ap-south-1`, output `json`). Delete the access key when
  Step 8 is finished.
- *IAM Identity Center:* `aws configure sso --profile thesis`, then `make aws-login` when the
  session expires.

**.env** — add (or check) these two lines:

```bash
AWS_THESIS_PROFILE=thesis
ALERT_EMAIL=your.real@address        # alerts and approval requests arrive here
```

## Run

```bash
make aws-whoami          # must show YOUR account id (not 000000000000)
make aws-bootstrap       # once per account/region (CDK's S3 bucket and roles)
make aws-deploy          # about 5 min; 5 stacks incl. DcSelfheal-dev-Iot
#   -> confirm the "AWS Notification - Subscription Confirmation" email
make aws-devices         # certificate for the gateways -> certs/ (never commit or share)
make aws-check           # E2E: CRAH failure fixed via IoT Core shadows + approval via the public URL
make aws-loadtest        # E2: 50, 500, 2,000 gateways x 30 min (about 1 h 45 min); MINUTES=10 is quicker
make aws-cost            # E3 model, now with the usage measured by the load test
make aws-destroy         # deletes the certificate and every stack: charges stop
```

The load test prints its cost estimate and asks for "yes". To run it in the background (so an SSH
disconnect does not stop it), check the estimate first, answer anything but yes, then:
`nohup make aws-loadtest YES=1 > loadtest.log 2>&1 &`.

A day or two later (Cost Explorer lags about a day):

1. Billing console → *Cost allocation tags* → activate the user-defined tag **Project**
   (every resource is tagged `Project=dc-selfheal`).
2. `make aws-bill START=<first day of the AWS work>` → `experiments/results/e3_measured.md`.

## What the checks show

`make aws-check` runs the same two checks as on LocalStack, now through IoT Core:

- commands through device shadows (one written while the gateway was offline), telemetry stored
  and processed for every gateway, CRAH 2 failure detected, the playbook mitigates it with no human
  input, standby running, zone inlets back below 27 °C, no escalation;
- the latency split **gateway → IoT Core → Lambda → handler**, and **sensor message → first
  command at the gateway** (the proposal's end-to-end latency);
- the approval check: a high-risk plan waits, the email/URL link shows the plan, the POST approves,
  the link cannot be reused, the plan is rechecked and executed.

`make aws-loadtest` pauses the playbook rule (no incidents or emails for virtual gateways) and
re-enables it afterwards; results go to `experiments/results/e2_summary.md` and `e2_runs.csv`.
It also reads the account's Lambda concurrency limit: new accounts sometimes start at 10
concurrent executions. If the 2,000-gateway level shows Lambda throttles, that limit is the
reason; it can be raised in *Service Quotas → AWS Lambda → Concurrent executions* (free, may take
a day), and the summary's extrapolation to 10,000 gateways states the concurrency required.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `aws-whoami` shows 000000000000 or "test" | the LocalStack keys leaked in: run the target via make, not by hand |
| `ProfileNotFound` | create the profile (above) or set `AWS_THESIS_PROFILE` |
| Gateways cannot connect | run `make aws-devices` after `aws-deploy`; check `certs/endpoint.txt` |
| No alert or approval email | confirm the SNS subscription email; check spam |
| Stack deletion fails on the bucket | re-run `make aws-destroy` (the bucket is emptied automatically) |

After `aws-destroy` only CDK's bootstrap stack (`CDKToolkit`) remains; it costs close to nothing
and can be deleted in the CloudFormation console if you will not deploy again.
