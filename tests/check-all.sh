#!/bin/bash
# Quick verification: imports + daemon tests + contract tests
set -e
echo "=== Import check ==="
python3 -c "import railway.app; print('Railway OK')"
echo ""
echo "=== Daemon tests ==="
# Keep daemon quick checks isolated from tests/conftest.py, which pulls browser fixtures.
python3 -m pytest tests/daemon/ -q \
  --ignore=tests/daemon/test_daemon.py \
  --ignore=tests/daemon/transcript/ \
  -m "not nightly" \
  --confcutdir=tests/daemon
echo ""
echo "=== Contract tests ==="
python3 -m pytest tests/daemon/test_api_contract.py tests/daemon/test_ws_contract.py \
  tests/daemon/test_railway_ws_contract.py tests/daemon/test_railway_rest_contract.py -v \
  --confcutdir=tests/daemon
echo ""
echo "=== Architecture contracts (Structurizr -> Import Linter) ==="
python3 -m pytest tests/docs/test_structurizr_import_linter.py -q
