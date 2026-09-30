#!/usr/bin/env bash
# Checks that the local stack works end to end.
# 1) LocalStack is healthy  2) MQTT round trip works  3) foundation stack deployed
set -uo pipefail

cd "$(dirname "$0")/.."
set -a; [[ -f .env ]] && . ./.env; set +a
export AWS_ENDPOINT_URL="http://localhost:4566"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION}}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
echo "Region: ${AWS_REGION}"

pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAILED=1; }
FAILED=0

echo "1. LocalStack health"
health="$(curl -fs http://localhost:4566/_localstack/health || true)"
if [[ -n "${health}" ]]; then
  pass "LocalStack is up (edition: $(echo "${health}" | jq -r '.edition // "unknown"'))"
  for svc in lambda stepfunctions dynamodb events sns sqs s3; do
    state="$(echo "${health}" | jq -r --arg s "${svc}" '.services[$s] // "missing"')"
    if [[ "${state}" == "available" || "${state}" == "running" ]]; then pass "${svc}: ${state}"; else fail "${svc}: ${state}"; fi
  done
else
  fail "LocalStack not reachable on localhost:4566 (run: make up)"
fi

echo "2. MQTT round trip via Mosquitto"
msg="smoke-$(date +%s)"
got="$(timeout 10 mosquitto_sub -h 127.0.0.1 -p 1883 -t dc/smoke -C 1 & sleep 1; \
       mosquitto_pub -h 127.0.0.1 -p 1883 -t dc/smoke -m "${msg}"; wait)"
if [[ "${got}" == *"${msg}"* ]]; then pass "published and received '${msg}'"; else fail "no MQTT message received"; fi

echo "3. Foundation stack on LocalStack"
status="$(aws cloudformation describe-stacks --stack-name DcSelfheal-local-Foundation \
          --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_DEPLOYED")"
if [[ "${status}" == "CREATE_COMPLETE" || "${status}" == "UPDATE_COMPLETE" ]]; then
  pass "stack status ${status}"
  bucket="$(aws cloudformation describe-stacks --stack-name DcSelfheal-local-Foundation \
            --query "Stacks[0].Outputs[?OutputKey=='ArtifactsBucketName'].OutputValue" --output text)"
  echo "hello" | aws s3 cp - "s3://${bucket}/smoke.txt" >/dev/null && pass "wrote to bucket ${bucket}" || fail "could not write to bucket"
else
  fail "stack status ${status} (run: make deploy-local)"
fi

echo
if [[ "${FAILED}" == "0" ]]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; exit 1; fi
