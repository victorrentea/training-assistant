#!/bin/bash
# Production health check wrapper — runs the Playwright-based UI check
# Exit 0 = healthy, Exit 1 = failure detected
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/railway/healthcheck.py" "$@"
