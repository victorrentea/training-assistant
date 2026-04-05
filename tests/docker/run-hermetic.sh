#!/bin/bash
# Run hermetic Docker tests with output to logs/
# Usage: bash tests/docker/run-hermetic.sh [extra pytest args...]
set -e
mkdir -p logs
bash tests/docker/build-daemon.sh -v --tb=short "$@" 2>&1 | tee logs/hermetic-latest.txt
echo ""
echo "=== Results saved to logs/hermetic-latest.txt ==="
tail -5 logs/hermetic-latest.txt
