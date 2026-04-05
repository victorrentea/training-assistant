#!/bin/bash
# Run daemon unit tests (fast, no Docker needed)
# Usage: bash tests/run-daemon-tests.sh [extra pytest args...]
python3 -m pytest tests/daemon/ -q \
  --ignore=tests/daemon/test_daemon.py \
  --ignore=tests/daemon/transcript/ \
  -m "not nightly" "$@"
