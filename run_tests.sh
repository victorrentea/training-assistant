#!/bin/bash
set -e

echo "=== Unit tests ==="
pytest test_main.py -v

echo ""
echo "=== JS unit tests ==="
node test_participant_js.js

echo ""
echo "=== E2E browser tests ==="
pytest test_e2e.py -v

echo ""
echo "All tests passed."
