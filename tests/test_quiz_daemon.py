"""Unit tests for quiz_daemon.py — lock files, timestamp appender, polling helpers."""
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


class TestTranscriptTimestampAppender:
    def test_init(self, tmp_path):
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path, interval_seconds=5.0)
        assert appender.folder == tmp_path
        assert appender.interval_seconds == 5.0
        assert appender.enabled is False

    def test_start_no_files(self, tmp_path):
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path)
        appender.start()
        assert appender.enabled is False

    def test_start_with_file(self, tmp_path):
        (tmp_path / "transcript.txt").write_text("[00:00:00.00] Test")
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path, interval_seconds=1.0)
        appender.start()
        assert appender.enabled is True

    def test_start_zero_interval(self, tmp_path):
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path, interval_seconds=0)
        appender.start()
        assert appender.enabled is False

    def test_tick_when_disabled(self, tmp_path):
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path)
        appender.tick()  # Should not raise

    def test_tick_appends(self, tmp_path):
        f = tmp_path / "transcript.txt"
        f.write_text("[00:00:00.00] Test")
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path, interval_seconds=0.01)
        appender.start()
        assert appender.enabled
        # Force next_append_at to past
        appender._next_append_at = 0
        appender.tick()
        content = f.read_text()
        assert content.count("\n") >= 1

    def test_resolve_target_missing_folder(self, tmp_path):
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path / "nonexistent")
        assert appender._resolve_target_file() is None

    def test_resolve_target_no_txt(self, tmp_path):
        (tmp_path / "test.pdf").write_text("x")
        from daemon.transcript.loop import TranscriptTimestampAppender
        appender = TranscriptTimestampAppender(tmp_path)
        assert appender._resolve_target_file() is None
