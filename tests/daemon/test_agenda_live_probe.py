"""Unit tests: agenda .docx is probed live in the main loop, like notes/summary.

Regression for: an agenda dropped into the session folder after the daemon started
was not picked up until restart, because the agenda path was only resolved at startup
and session-create — never re-probed. These tests pin the probe/change-detection/broadcast
behaviour that makes the agenda behave exactly like notes and ai-summary.
"""
from pathlib import Path
from unittest.mock import patch

from daemon.__main__ import (
    _agenda_path_from_probe,
    _broadcast_notes_summary_counts,
    _build_notes_summary_probe,
    _probe_change_parts,
)
from daemon.ws_messages import AgendaUpdatedMsg


def _write_agenda(folder: Path, name: str = "agenda.docx") -> Path:
    p = folder / name
    p.write_bytes(b"PK\x03\x04 fake docx")
    return p


class TestAgendaProbe:
    def test_probe_has_no_agenda_when_absent(self, tmp_path):
        probe = _build_notes_summary_probe(tmp_path)
        assert probe["agenda_file"] is None
        assert probe["agenda_mtime_ns"] is None

    def test_probe_detects_agenda_file(self, tmp_path):
        agenda = _write_agenda(tmp_path)
        probe = _build_notes_summary_probe(tmp_path)
        assert probe["agenda_file"] == str(agenda)
        assert probe["agenda_mtime_ns"] is not None

    def test_change_parts_reports_agenda_on_add(self, tmp_path):
        before = _build_notes_summary_probe(tmp_path)
        _write_agenda(tmp_path)
        after = _build_notes_summary_probe(tmp_path)
        assert "agenda" in _probe_change_parts(before, after)

    def test_change_parts_reports_agenda_on_remove(self, tmp_path):
        _write_agenda(tmp_path)
        before = _build_notes_summary_probe(tmp_path)
        (tmp_path / "agenda.docx").unlink()
        after = _build_notes_summary_probe(tmp_path)
        assert "agenda" in _probe_change_parts(before, after)

    def test_change_parts_ignores_unchanged_agenda(self, tmp_path):
        _write_agenda(tmp_path)
        before = _build_notes_summary_probe(tmp_path)
        after = _build_notes_summary_probe(tmp_path)
        assert "agenda" not in _probe_change_parts(before, after)

    def test_agenda_path_from_probe_roundtrip(self, tmp_path):
        assert _agenda_path_from_probe(_build_notes_summary_probe(tmp_path)) is None
        agenda = _write_agenda(tmp_path)
        assert _agenda_path_from_probe(_build_notes_summary_probe(tmp_path)) == agenda


class TestAgendaBroadcast:
    def test_broadcasts_agenda_present_on_add(self, tmp_path):
        _write_agenda(tmp_path)
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "agenda")
        agenda_msgs = [c.args[0] for c in mock.call_args_list
                       if isinstance(c.args[0], AgendaUpdatedMsg)]
        assert len(agenda_msgs) == 1
        assert agenda_msgs[0].has_agenda is True

    def test_broadcasts_agenda_absent_on_remove(self, tmp_path):
        # Agenda removed and nothing else present: must STILL broadcast has_agenda=False
        # so the nav hides. The all-absent guard only suppresses the first "initial" probe.
        probe = _build_notes_summary_probe(tmp_path)  # empty folder
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "agenda")
        agenda_msgs = [c.args[0] for c in mock.call_args_list
                       if isinstance(c.args[0], AgendaUpdatedMsg)]
        assert len(agenda_msgs) == 1
        assert agenda_msgs[0].has_agenda is False

    def test_initial_empty_probe_is_silent(self, tmp_path):
        # Fresh start with nothing present must not emit any broadcast (participants
        # already receive nulls/false from GET /api/participant/state).
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "initial")
        assert mock.call_count == 0

    def test_no_agenda_broadcast_when_only_notes_changed(self, tmp_path):
        _write_agenda(tmp_path)
        (tmp_path / "notes.txt").write_text("a line")
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as mock:
            _broadcast_notes_summary_counts(probe, "notes")
        assert not [c.args[0] for c in mock.call_args_list
                    if isinstance(c.args[0], AgendaUpdatedMsg)]
