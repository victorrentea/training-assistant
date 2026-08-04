"""Unit tests: opened-files.md count is probed live in the main loop, like notes/summary/agenda.

Pins the probe/change-detection/broadcast behaviour that powers the participant
"Files" count badge — a file opened mid-session is detected by the main-loop probe
and broadcast as FilesCountUpdatedMsg, without a daemon restart.
"""
from pathlib import Path
from unittest.mock import patch

from daemon import files_md
from daemon.__main__ import (
    _broadcast_notes_summary_counts,
    _build_notes_summary_probe,
    _probe_change_parts,
)
from daemon.ws_messages import FilesCountUpdatedMsg


def _write_files(folder: Path, n: int) -> None:
    if n:
        entries = [
            files_md.Entry(
                path=f"f{i}.py",
                branch="main",
                ts=f"2026-05-27T10:0{i}:00Z",
                blob_url=f"https://github.com/o/r/blob/main/f{i}.py",
                ref="branch",
            )
            for i in range(n)
        ]
        doc = files_md.Doc(repos=[
            files_md.Repo("https://github.com/o/r", "r", "main", "main", entries)
        ])
    else:
        doc = files_md.Doc()
    (folder / "opened-files.md").write_text(doc.render(), encoding="utf-8")


class TestFilesProbe:
    def test_probe_has_no_files_when_absent(self, tmp_path):
        probe = _build_notes_summary_probe(tmp_path)
        assert probe["files_file"] is None
        assert probe["files_mtime_ns"] is None
        assert probe["files_count"] == 0

    def test_probe_detects_files(self, tmp_path):
        _write_files(tmp_path, 2)
        probe = _build_notes_summary_probe(tmp_path)
        assert probe["files_file"] == str(tmp_path / "opened-files.md")
        assert probe["files_mtime_ns"] is not None
        assert probe["files_count"] == 2

    def test_change_parts_reports_files_on_add(self, tmp_path):
        before = _build_notes_summary_probe(tmp_path)
        _write_files(tmp_path, 1)
        after = _build_notes_summary_probe(tmp_path)
        assert "files" in _probe_change_parts(before, after)

    def test_change_parts_reports_files_on_count_change(self, tmp_path):
        _write_files(tmp_path, 1)
        before = _build_notes_summary_probe(tmp_path)
        _write_files(tmp_path, 3)
        after = _build_notes_summary_probe(tmp_path)
        assert "files" in _probe_change_parts(before, after)

    def test_change_parts_ignores_unchanged_files(self, tmp_path):
        _write_files(tmp_path, 2)
        before = _build_notes_summary_probe(tmp_path)
        after = _build_notes_summary_probe(tmp_path)
        assert "files" not in _probe_change_parts(before, after)


class TestFilesBroadcast:
    def test_broadcasts_files_count_on_add(self, tmp_path):
        _write_files(tmp_path, 2)
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "files")
        msgs = [c.args[0] for c in mock.call_args_list
                if isinstance(c.args[0], FilesCountUpdatedMsg)]
        assert len(msgs) == 1
        assert msgs[0].count == 2

    def test_initial_empty_probe_is_silent(self, tmp_path):
        # Fresh start with nothing present emits no broadcast (participants already
        # receive files_count=0 from GET /api/participant/state).
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "initial")
        assert [c.args[0] for c in mock.call_args_list
                if isinstance(c.args[0], FilesCountUpdatedMsg)] == []

    def test_initial_with_files_present_broadcasts_count(self, tmp_path):
        # Daemon restart with files already present must seed the count to participants.
        _write_files(tmp_path, 1)
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "initial")
        msgs = [c.args[0] for c in mock.call_args_list
                if isinstance(c.args[0], FilesCountUpdatedMsg)]
        assert len(msgs) == 1
        assert msgs[0].count == 1

    def test_no_files_broadcast_when_only_notes_changed(self, tmp_path):
        _write_files(tmp_path, 1)
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "notes")
        assert not [c.args[0] for c in mock.call_args_list
                    if isinstance(c.args[0], FilesCountUpdatedMsg)]
