#!/bin/bash
set -e

echo "=== Unit tests ==="
pytest tests/test_main.py -v

echo ""
echo "=== JS unit tests ==="
node tests/test_participant_js.js

echo ""
echo "=== E2E browser tests ==="
pytest tests/test_e2e.py -v

echo ""
echo "=== Load test (${LOAD_TEST_COUNT:-30} participants) ==="
pytest tests/test_load.py -v -s

echo ""
echo "All tests passed."
