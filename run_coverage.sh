#!/bin/bash
# Run e2e tests with backend (server-side) code coverage.
# Usage: ./run_coverage.sh [pytest args...]
#
# The server subprocess runs under `coverage run`, then results are combined.

set -e
cd "$(dirname "$0")"

# Clean previous coverage data
rm -f .coverage .coverage.server .coverage.combined

# Tell conftest to launch uvicorn under coverage
export _E2E_COVERAGE=1

# Run tests (pass any extra pytest args through)
python3 -m pytest "$@" || true

# Wait a moment for .coverage.server to be flushed
sleep 1

if [ -f .coverage.server ]; then
    echo ""
    echo "=== Backend (server-side) coverage ==="
    python3 -m coverage report --data-file=.coverage.server \
        --omit="test_*,conftest.py,pages/*,quiz_generator.py" \
        --show-missing
else
    echo "WARNING: .coverage.server not found — server may not have exited cleanly"
fi
