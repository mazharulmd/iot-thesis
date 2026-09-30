#!/usr/bin/env bash
# One-time setup for an Ubuntu 24.04 server (x86_64 or ARM64 / OCI Ampere).
# Installs: Docker Engine + Compose plugin, Node.js 22, AWS CLI v2,
#           CDK CLI, cdklocal, awslocal, Python venv tooling, mosquitto clients.
# Usage:  bash scripts/setup-server.sh      (then log out and back in)
set -euo pipefail

ARCH="$(uname -m)"
echo ">> Architecture: ${ARCH}"

echo ">> Base packages"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg unzip git make jq \
  python3 python3-venv python3-pip mosquitto-clients

echo ">> Docker Engine (official repository)"
if ! command -v docker >/dev/null 2>&1; then
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo usermod -aG docker "$USER"

echo ">> Node.js 22 LTS"
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v)" != v22* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

echo ">> CDK CLI and cdklocal"
sudo npm install -g aws-cdk aws-cdk-local

echo ">> AWS CLI v2"
if ! command -v aws >/dev/null 2>&1; then
  tmp="$(mktemp -d)"
  if [[ "${ARCH}" == "aarch64" ]]; then
    url="https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip"
  else
    url="https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"
  fi
  curl -fsSL "${url}" -o "${tmp}/awscliv2.zip"
  unzip -q "${tmp}/awscliv2.zip" -d "${tmp}"
  sudo "${tmp}/aws/install"
  rm -rf "${tmp}"
fi

echo ">> awslocal (wrapper that points the AWS CLI at LocalStack)"
python3 -m pip install --user --break-system-packages awscli-local

echo
echo "Done. Log out and back in (so the docker group applies), then run:"
echo "  cd dc-selfheal && make venv && make up && make smoke"
