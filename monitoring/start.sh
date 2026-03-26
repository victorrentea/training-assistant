#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_FILE="${TRAINING_ASSISTANTS_SECRETS_FILE:-$HOME/.training-assistants-secrets.env}"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "Error: $SECRETS_FILE not found. Create it with HOST_USERNAME and HOST_PASSWORD."
    exit 1
fi

# Load secrets
set -a
source "$SECRETS_FILE"
set +a

cd "$SCRIPT_DIR"
docker compose up -d

echo ""
echo "Grafana:    http://localhost:3000  (no login required)"
echo "Prometheus: http://localhost:9090"
