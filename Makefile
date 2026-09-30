# Common commands for dc-selfheal.  Run `make help` to list them.
SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
# Load .env if present and export its variables to every command.
ifneq (,$(wildcard .env))
include .env
export
endif
# One region everywhere.  cdklocal drops AWS_* variables unless allow-listed,
# which would otherwise make it deploy to us-east-1.
AWS_DEFAULT_REGION ?= ap-south-1
AWS_REGION ?= $(AWS_DEFAULT_REGION)
export AWS_DEFAULT_REGION AWS_REGION
export AWS_ENVAR_ALLOWLIST := AWS_REGION,AWS_DEFAULT_REGION

.PHONY: help venv test up down logs status deploy-local destroy-local smoke clean-local sim sim-all pipeline-up pipeline-down status-pipeline cmd e2e reset-shadows train evaluate skab build-lambdas events remove-step3-stack incidents incident locks reset-locks playbook playbook-eval approvals approve reject guardrails reset-breaker e2e-approval aws-login aws-whoami aws-bootstrap aws-deploy aws-devices aws-check aws-loadtest aws-cost aws-bill aws-destroy experiments e1 analysis live-experiment latency warm

help:          ## List available commands
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-15s %s\n",$$1,$$2}'

venv:          ## Create Python virtual environment and install dependencies
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt -r requirements-dev.txt -r requirements-sim.txt -r requirements-ml.txt

test:          ## Run unit tests
	$(VENV)/bin/pytest -q

up:            ## Start LocalStack and Mosquitto
	mkdir -p .localstack .mosquitto/data
	docker compose up -d
	@echo "Waiting for LocalStack to become healthy..."
	@for i in $$(seq 1 30); do \
	  curl -fs http://localhost:4566/_localstack/health >/dev/null && echo "LocalStack ready" && exit 0; \
	  sleep 4; done; echo "LocalStack did not start - run: make logs"; exit 1

down:          ## Stop the local stack (data is kept)
	docker compose down

logs:          ## Follow LocalStack logs
	docker compose logs -f localstack

status:        ## Show container status and LocalStack service health
	docker compose ps
	@curl -fs http://localhost:4566/_localstack/health | jq '.services' || true

deploy-local: build-lambdas ## Bootstrap (first time) and deploy all stacks to LocalStack
	source $(VENV)/bin/activate && cdklocal bootstrap -c stage=local
	source $(VENV)/bin/activate && cdklocal deploy --all --require-approval never \
	  -c stage=local -c alert_email=$(ALERT_EMAIL)

destroy-local: ## Remove all stacks from LocalStack
	source $(VENV)/bin/activate && cdklocal destroy --all --force -c stage=local

smoke:         ## End-to-end check of the local environment
	bash scripts/smoke-test.sh

clean-local:   ## Stop containers and DELETE all local data
	docker compose down -v
	rm -rf .localstack .mosquitto


sim:           ## Run one scenario:  make sim S=crah_fan_failure
	$(PY) -m simulator.run simulator/scenarios/$(S).yaml --both

sim-all:       ## Run every scenario with and without remediation (outputs in runs/)
	$(PY) -m simulator.run --all --both

SPEED ?= 1
pipeline-up:   ## Start bridge + live simulator in the background (SPEED=1 by default)
	@mkdir -p logs .run
	@if [ -f .run/bridge.pid ]; then echo "already running (make pipeline-down first)"; exit 1; fi
	nohup $(PY) -m bridge --stage local > logs/bridge.log 2>&1 & echo $$! > .run/bridge.pid
	@for i in $$(seq 1 30); do grep -q "connected to MQTT" logs/bridge.log && break; sleep 1; done; \
	 grep -q "connected to MQTT" logs/bridge.log || { echo "bridge did not start - see logs/bridge.log"; exit 1; }
	$(PY) -m tools.reset_shadows
	$(PY) -m tools.prepare_run
	$(PY) -m tools.warm
	nohup $(PY) -m simulator.live --speed $(SPEED) --duration 0 > logs/live.log 2>&1 & echo $$! > .run/live.pid
	@for i in $$(seq 1 60); do grep -q "^live:" logs/live.log && break; sleep 1; done; \
	 grep -q "^live:" logs/live.log || { echo "simulator did not connect - see logs/live.log"; exit 1; }
	@echo "Pipeline running and connected. Logs: logs/bridge.log, logs/live.log   Status: make status-pipeline"

pipeline-down: ## Stop bridge + live simulator
	-@for p in live bridge; do [ -f .run/$$p.pid ] && kill $$(cat .run/$$p.pid) 2>/dev/null; rm -f .run/$$p.pid; done
	@echo "Pipeline stopped."

status-pipeline: ## Per-gateway message counts, latency and shadow state
	$(PY) -m tools.status --stage local

cmd:           ## Send a command:  make cmd A=crah1 D='{"fan_pct": 70}'
	$(PY) -m tools.send_command $(A) '$(D)'

reset-shadows: ## Clear all gateway shadows (bridge must be running)
	$(PY) -m tools.reset_shadows

e2e-approval:  ## Live check of a high-risk playbook: waits, approved via the URL, then acts
	$(PY) -m tools.e2e_approval

e2e:           ## End-to-end check incl. live CRAH failure and latency (starts and stops its own pipeline)
	$(PY) -m tools.e2e_check

train:         ## Train D1/D2 on normal simulator data (writes detection/models/)
	$(PY) -m detection.train

evaluate:      ## Offline evaluation of D0/D1/D2/D1h/D2h on all faults (writes detection/results/)
	$(PY) -m detection.evaluate

skab:          ## Validate the detector families on the real SKAB pump benchmark
	$(PY) -m detection.skab

build-lambdas: ## Package the detector and remediation Lambdas into build/
	$(PY) -m tools.build_lambda

events:        ## Show anomaly events (make events F=1 to keep following)
	$(PY) -m tools.events $(if $(F),--follow,)

EXP_SEEDS ?= 20
WORKERS ?= $(shell n=$$(nproc); [ $$n -gt 1 ] && echo $$((n - 1)) || echo 1)
SUITE ?= all
LIVE_MODES ?= M1,M2,M3
LIVE_SEEDS ?= 1
experiments:   ## All experiment suites offline (E1, M1 sensitivity, E4), then tables + figures
	$(PY) -m experiments.batch --suite $(SUITE) --seeds $(EXP_SEEDS) --workers $(WORKERS)
	$(PY) -m experiments.analysis

e1:            ## Only E1 (8 faults x 3 modes x 20 seeds), then tables + figures
	$(PY) -m experiments.batch --suite e1 --seeds $(EXP_SEEDS) --workers $(WORKERS)
	$(PY) -m experiments.analysis

analysis:      ## Tables, tests and figures from experiments/results/runs.csv
	$(PY) -m experiments.analysis

live-experiment: ## Live fidelity runs on LocalStack (8 faults x LIVE_MODES x LIVE_SEEDS, ~4.5 min each)
	$(PY) -m tools.live_experiment --modes $(LIVE_MODES) --seeds $(LIVE_SEEDS)
	$(PY) -m experiments.analysis

SPEEDS ?= 1,5,10
WINDOW ?= 60
incidents:     ## List remediation incidents (newest first)
	$(PY) -m tools.incidents

incident:      ## One incident's audit trail:  make incident I=<incident id>
	$(PY) -m tools.incidents --id $(I)

locks:         ## Show asset locks held by incidents
	$(PY) -m tools.incidents --locks

reset-locks:   ## Release all asset locks (between experiment runs)
	$(PY) -m tools.incidents --reset-locks

approvals:     ## High-risk plans waiting for a human (with their approval links)
	$(PY) -m tools.approve --pending

approve:       ## Approve a waiting plan:  make approve I=<incident id>
	$(PY) -m tools.approve --id $(I)

reject:        ## Reject a waiting plan:   make reject I=<incident id>
	$(PY) -m tools.approve --id $(I) --reject

guardrails:    ## Rate-limit and circuit-breaker state per asset
	$(PY) -m tools.incidents --guardrails

reset-breaker: ## Close an asset's circuit breaker after repair:  make reset-breaker A=crah2
	$(PY) -m tools.incidents --reset-breaker $(A)

playbook:      ## Offline closed-loop run, no AWS:  make playbook S=pump_degradation [A=notify] [O=approve|reject|none]
	$(PY) -m experiments.closed_loop --scenario $(S) --automation $(or $(A),on) --operator $(or $(O),approve)

playbook-eval: ## All faults x 5 seeds through the offline closed loop (about 6 min)
	$(PY) -m experiments.playbook_eval

latency:       ## Latency probe at several speeds:  make latency [SPEEDS=1,5,10] [WINDOW=60]
	$(PY) -m tools.latency --speeds $(SPEEDS) --window $(WINDOW)

warm:          ## Pre-warm the detector Lambda (pipeline-up does this too)
	$(PY) -m tools.warm

remove-step3-stack: ## One-time: delete the old Step 3 ingest stack (replaced by the Detection stack)
	AWS_ENDPOINT_URL=http://localhost:4566 aws cloudformation delete-stack --stack-name DcSelfheal-local-Ingest
	@echo "Old DcSelfheal-local-Ingest stack deleted."

# ------------------------------------------------------------------ real AWS (Step 8)
# .env holds LocalStack's dummy keys; these targets drop them and use your AWS profile instead
# (AWS_THESIS_PROFILE in .env, default "thesis"; it is not called AWS_PROFILE so that the
# LocalStack targets are never affected by it).
AWS_STAGE ?= dev
AWS_THESIS_PROFILE ?= thesis
DEVICES ?= 50,500,2000
MINUTES ?= 30
AWSENV := env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u AWS_ENDPOINT_URL \
  AWS_PROFILE=$(AWS_THESIS_PROFILE)

aws-login:     ## Sign in with IAM Identity Center (profile AWS_THESIS_PROFILE)
	$(AWSENV) aws sso login --use-device-code

aws-whoami:    ## Show which AWS account and identity the aws-* targets use
	$(AWSENV) aws sts get-caller-identity

aws-bootstrap: ## One-time CDK bootstrap of the AWS account/region
	source $(VENV)/bin/activate && $(AWSENV) cdk bootstrap -c stage=$(AWS_STAGE)

aws-deploy: build-lambdas ## Deploy all stacks to real AWS (on-demand tables, IoT Core)
	source $(VENV)/bin/activate && $(AWSENV) cdk deploy --all --require-approval never \
	  -c stage=$(AWS_STAGE) -c alert_email=$(ALERT_EMAIL) -c ddb_billing=on_demand

aws-devices:   ## Create the gateways' X.509 certificate (writes certs/)
	$(AWSENV) $(PY) -m tools.aws_devices create --stage $(AWS_STAGE)

aws-check:     ## End-to-end checks on AWS: CRAH failure fixed, approval via the public URL
	$(AWSENV) $(PY) -m tools.e2e_check --stage $(AWS_STAGE)
	$(AWSENV) $(PY) -m tools.e2e_approval --stage $(AWS_STAGE)

aws-loadtest:  ## E2 load test on IoT Core:  make aws-loadtest [DEVICES=50,500,2000] [MINUTES=30] [YES=1]
	$(AWSENV) $(PY) -m tools.loadgen --stage $(AWS_STAGE) --devices $(DEVICES) --minutes $(MINUTES) $(if $(YES),--yes,)

aws-cost:      ## E3 cost model (uses e2_usage.json from the load test if present)
	$(PY) -m experiments.cost_model

aws-bill:      ## E3 measured cost from Cost Explorer:  make aws-bill START=2026-10-01
	$(AWSENV) $(PY) -m tools.cost_report --stage $(AWS_STAGE) --start $(START)

aws-destroy: build-lambdas ## Delete the certificate and every stack on AWS (stops all charges)
	-$(AWSENV) $(PY) -m tools.aws_devices delete --stage $(AWS_STAGE)
	source $(VENV)/bin/activate && $(AWSENV) cdk destroy --all --force -c stage=$(AWS_STAGE)
