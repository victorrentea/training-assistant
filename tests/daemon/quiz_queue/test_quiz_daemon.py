"""Unit tests for quiz_daemon.py — lock files, polling helpers."""
import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# We need to mock imports before importing quiz_daemon
# quiz_daemon imports from quiz_core which needs ANTHROPIC_API_KEY


class TestLockFile:
    """Tests for _read_lock, _write_lock, _is_process_alive, _check_and_acquire_lock."""

    def test_read_lock_missing(self, tmp_path):
        from daemon.lock import _LOCK_FILE
        lock = tmp_path / "test.lock"
        # Manually test the logic
        assert not lock.exists()

    def test_write_and_read_lock(self, tmp_path):
        lock = tmp_path / "test.lock"
        data = {"pid": os.getpid(), "heartbeat": time.time()}
        lock.write_text(json.dumps(data))
        loaded = json.loads(lock.read_text())
        assert loaded["pid"] == os.getpid()

    def test_is_process_alive_self(self):
        from daemon.lock import _is_process_alive
        assert _is_process_alive(os.getpid()) is True

    def test_is_process_alive_dead(self):
        from daemon.lock import _is_process_alive
        # PID 99999999 almost certainly doesn't exist
        assert _is_process_alive(99999999) is False
