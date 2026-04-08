#!/bin/bash
# Run daemon unit tests (fast, no Docker needed)
# Usage: bash tests/run-daemon-tests.sh [extra pytest args...]
# Keep daemon-only runs isolated from tests/conftest.py browser fixtures.
python3 -m pytest tests/daemon/ -q \
  --ignore=tests/daemon/test_daemon.py \
  --ignore=tests/daemon/transcript/ \
  -m "not nightly" \
  --confcutdir=tests/daemon "$@"
