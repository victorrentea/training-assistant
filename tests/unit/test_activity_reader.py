"""Unit tests for daemon.slides.activity_reader."""
import textwrap
from datetime import date, datetime
from pathlib import Path

import pytest

from daemon.slides.activity_reader import _parse_seconds, _should_include, read_slides_log


# ── Duration parsing ──────────────────────────────────────────────────────────

def test_parse_seconds_full():
    assert _parse_seconds("86m7s") == 86 * 60 + 7

def test_parse_seconds_minutes_only():
    assert _parse_seconds("2m") == 120

def test_parse_seconds_seconds_only():
    assert _parse_seconds("13s") == 13

def test_parse_seconds_large():
    assert _parse_seconds("1436m27s") == 1436 * 60 + 27

def test_parse_seconds_invalid():
    assert _parse_seconds("bad") == 0


# ── Session filtering ─────────────────────────────────────────────────────────

_SESSION_DATE = date(2026, 4, 6)

def _dt(h, m, s=0):
    return datetime(_SESSION_DATE.year, _SESSION_DATE.month, _SESSION_DATE.day, h, m, s)


def test_should_include_before_session_start():
    entry = {"started_at": "2026-04-06T14:00:00", "paused_intervals": []}
    assert not _should_include(_dt(9, 0), entry)

def test_should_include_after_session_start():
    entry = {"started_at": "2026-04-06T14:00:00", "paused_intervals": []}
    assert _should_include(_dt(15, 0), entry)

def test_should_include_inside_closed_pause():
    entry = {
        "started_at": "2026-04-06T09:00:00",
        "paused_intervals": [{"from": "2026-04-06T12:00:00", "to": "2026-04-06T13:00:00"}],
    }
    assert not _should_include(_dt(12, 30), entry)

def test_should_include_after_closed_pause():
    entry = {
        "started_at": "2026-04-06T09:00:00",
        "paused_intervals": [{"from": "2026-04-06T12:00:00", "to": "2026-04-06T13:00:00"}],
    }
    assert _should_include(_dt(13, 30), entry)

def test_should_include_open_pause_not_excluded():
    """An open pause (to=None) should not filter out entries."""
    entry = {
        "started_at": "2026-04-06T09:00:00",
        "paused_intervals": [{"from": "2026-04-06T12:00:00", "to": None}],
    }
    assert _should_include(_dt(12, 30), entry)


# ── read_slides_log ───────────────────────────────────────────────────────────

def _write_activity_file(tmp_path: Path, content: str) -> Path:
    folder = tmp_path
    f = folder / f"activity-slides-{_SESSION_DATE.isoformat()}.md"
    f.write_text(textwrap.dedent(content), encoding="utf-8")
    return folder


def test_read_slides_log_basic(tmp_path):
    folder = _write_activity_file(tmp_path, """
        14:00:00 AI Coding.pptx - s59:5m, s60:30s
        AI Coding.pptx:60
    """)
    log = read_slides_log(folder, _SESSION_DATE, None)
    assert len(log) == 2
    files = {e["file"] for e in log}
    assert files == {"AI Coding.pptx"}
    by_slide = {e["slide"]: e["seconds_spent"] for e in log}
    assert by_slide[59] == 300
    assert by_slide[60] == 30


def test_read_slides_log_last_wins(tmp_path):
    """Latest line for same (timestamp, deck) overwrites earlier ones."""
    folder = _write_activity_file(tmp_path, """
        14:00:00 AI Coding.pptx - s59:1m
        14:00:00 AI Coding.pptx - s59:5m, s60:10s
    """)
    log = read_slides_log(folder, _SESSION_DATE, None)
    by_slide = {e["slide"]: e["seconds_spent"] for e in log}
    assert by_slide[59] == 300  # 5m, not 1m
    assert by_slide[60] == 10


def test_read_slides_log_session_filter(tmp_path):
    """Entries before session start are excluded."""
    folder = _write_activity_file(tmp_path, """
        09:00:00 AI Coding.pptx - s3:10m
        15:00:00 AI Coding.pptx - s59:2m
    """)
    session_entry = {"started_at": "2026-04-06T14:00:00", "paused_intervals": []}
    log = read_slides_log(folder, _SESSION_DATE, session_entry)
    assert len(log) == 1
    assert log[0]["slide"] == 59


def test_read_slides_log_no_file(tmp_path):
    log = read_slides_log(tmp_path, _SESSION_DATE, None)
    assert log == []


def test_read_slides_log_multiple_periods(tmp_path):
    """Multiple activity periods produce separate entries."""
    folder = _write_activity_file(tmp_path, """
        09:00:00 AI Coding.pptx - s1:10m
        15:00:00 AI Coding.pptx - s59:2m
    """)
    log = read_slides_log(folder, _SESSION_DATE, None)
    assert len(log) == 2
