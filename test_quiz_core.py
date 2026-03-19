# test_quiz_core.py
import pytest
from datetime import date
from pathlib import Path
import tempfile, os

from quiz_core import find_session_folder


def _make_folder(base: Path, name: str) -> Path:
    p = base / name
    p.mkdir()
    return p


def test_finds_single_day_folder(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-19 CleanCode@acme")
    notes = folder / "notes.txt"
    notes.write_text("agenda")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf == folder
    assert sn == notes


def test_no_match_outside_range(tmp_path):
    _make_folder(tmp_path, "2026-03-19 Workshop")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 20))
    assert sf is None and sn is None


def test_multi_day_range_dd(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-18..21 Workshop")
    (folder / "notes.txt").write_text("x")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 20))
    assert sf == folder


def test_multi_day_range_mm_dd(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-30..04-02 Workshop")
    (folder / "notes.txt").write_text("x")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 4, 1))
    assert sf == folder


def test_no_notes_file(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-19 Workshop")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf == folder
    assert sn is None


def test_missing_sessions_folder():
    os.environ["SESSIONS_FOLDER"] = "/nonexistent/path/xyz"
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf is None and sn is None


def test_multiple_matches_uses_latest_start(tmp_path):
    f1 = _make_folder(tmp_path, "2026-03-18..20 Workshop")
    f2 = _make_folder(tmp_path, "2026-03-19 Workshop")
    (f1 / "notes.txt").write_text("a")
    (f2 / "notes.txt").write_text("b")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf == f2  # latest start_date wins


def test_invalid_end_date_skipped(tmp_path):
    _make_folder(tmp_path, "2026-03-19..32 Workshop")  # day 32 invalid
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf is None


def test_uses_most_recently_modified_txt(tmp_path):
    import time
    folder = _make_folder(tmp_path, "2026-03-19 Workshop")
    old = folder / "old.txt"
    new = folder / "new.txt"
    old.write_text("old")
    time.sleep(0.01)
    new.write_text("new")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    _, sn = find_session_folder(date(2026, 3, 19))
    assert sn == new
