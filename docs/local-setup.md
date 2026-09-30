# Local setup on an Ubuntu 24.04 server

The whole project runs on one Ubuntu server during development:

| Component | Runs as | Replaces on AWS |
| --- | --- | --- |
| LocalStack | Docker container, port 4566 | Lambda, Step Functions, DynamoDB, EventBridge, SNS, SQS, S3 |
| Mosquitto | Docker container, port 1883 | AWS IoT Core (not in LocalStack's free plans) |
| Simulator, detectors | Python on the server | Same code |

Both ports listen on `127.0.0.1` only. Nothing is reachable from the internet.

## 1. Copy the project to the server

```bash
# on your laptop
scp dc-selfheal-step1-local.zip ubuntu@SERVER_IP:~
ssh ubuntu@SERVER_IP
unzip dc-selfheal-step1-local.zip && cd dc-selfheal
```

## 2. Install tools (once)

```bash
bash scripts/setup-server.sh
exit                      # log out so the docker group applies
ssh ubuntu@SERVER_IP && cd dc-selfheal
docker run --rm hello-world   # should print "Hello from Docker!"
```

## 3. Add your LocalStack token

```bash
cp .env.example .env
nano .env                 # paste LOCALSTACK_AUTH_TOKEN and your ALERT_EMAIL
chmod 600 .env
```

## 4. Start, deploy, check

```bash
make venv          # Python environment
make test          # expect: 3 passed
make up            # start LocalStack + Mosquitto
make deploy-local  # deploy the foundation stack to LocalStack
make smoke         # expect: ALL CHECKS PASSED
```

## Daily use

| Command | What it does |
| --- | --- |
| `make up` / `make down` | Start or stop the local stack (data is kept) |
| `make status` | Container status and service health |
| `make logs` | Follow LocalStack logs |
| `make smoke` | End-to-end check |
| `make clean-local` | Delete all local data and start fresh |

## Viewing web pages from your laptop

Use an SSH tunnel instead of opening firewall ports:

```bash
ssh -L 4566:localhost:4566 ubuntu@SERVER_IP
```

Then `http://localhost:4566/_localstack/health` works in your laptop browser.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `permission denied ... docker.sock` | Log out and in again after setup |
| LocalStack exits right after start | Check the token in `.env`; run `make logs` |
| `make smoke` fails on step 3 | Run `make deploy-local` first |
| ARM server (OCI Ampere) | Supported; later Lambda functions will be built for `arm64` |

## LocalStack gets slower over time

LocalStack saves its state only when it stops (`SNAPSHOT_SAVE_STRATEGY=ON_SHUTDOWN` in
`docker-compose.yml`). With the default (a snapshot every 15 s) each changed service is locked
while it saves, and as the Telemetry table grew, DynamoDB calls slowed from ~35 ms to seconds.
`make pipeline-up`, `make e2e` and `make latency` also delete telemetry older than 2 hours.

If calls are still slow, start from a clean state (the stacks are redeployed in about a minute;
results in `runs/`, `detection/results/` and `experiments/results/` are not touched):

```bash
make clean-local && make up && make deploy-local
```
