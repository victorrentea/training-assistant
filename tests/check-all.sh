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
echo "=== Frontend conventions ==="
# Static-only checks (no browser): keeps the single-tooltip rule enforced.
python3 -m pytest tests/frontend/ -q --confcutdir=tests/frontend
echo ""
echo "=== Participant tab routing (frontend/backend drift) ==="
# test_frontend_views_are_all_routable pins the SPA's VIEWS array to the gateway's
# _PARTICIPANT_TAB_SLUGS. The guard existed but ran in neither this hook nor CI, so
# a new tab shipped with a 404 deep link ("Report a bug", 2026-08-13). Cheap (<1s).
python3 -m pytest tests/features/pages/test_router.py -q
echo ""
echo "=== Architecture contracts (Structurizr -> Import Linter) ==="
python3 -m pytest tests/docs/test_structurizr_import_linter.py -q
echo ""
echo "=== C4 view exports freshness ==="
python3 -m pytest tests/docs/test_c4views_freshness.py -q
