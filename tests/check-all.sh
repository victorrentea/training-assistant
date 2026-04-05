#!/bin/bash
# Quick verification: imports + daemon tests + contract tests
set -e
echo "=== Import check ==="
python3 -c "import main; print('Railway OK')"
echo ""
echo "=== Daemon tests ==="
python3 -m pytest tests/daemon/ -q \
  --ignore=tests/daemon/test_daemon.py \
  --ignore=tests/daemon/transcript/ \
  -m "not nightly"
echo ""
echo "=== Contract tests ==="
python3 -m pytest tests/daemon/test_api_contract.py tests/daemon/test_ws_contract.py -v
