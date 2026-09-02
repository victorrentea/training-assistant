"""Unit tests: intercepted agent prompts are parsed out of the session notes and
probed live in the main loop, like notes/summary/agenda/files.

Pins what the participants' "Prompts" tab is built on: a 🤖-stamped line the
macOS addon appended to the notes file becomes one prompt entry, and the count
is broadcast as PromptsCountUpdatedMsg without a daemon restart.
"""
from unittest.mock import patch

from daemon.__main__ import (
    _broadcast_notes_summary_counts,
    _build_notes_summary_probe,
)
from daemon.misc.content_files import parse_prompts
from daemon.ws_messages import PromptsCountUpdatedMsg


def _write_notes(folder, text: str) -> None:
    (folder / "session - notes.txt").write_text(text, encoding="utf-8")


class TestParsePrompts:
    def test_no_notes(self):
        assert parse_prompts(None) == []
        assert parse_prompts("") == []

    def test_only_robot_lines_count(self):
        text = "- plain note\n- 📋 https://example.com\n- 🤖 start db,be,fe\n"
        assert parse_prompts(text) == ["start db,be,fe"]

    def test_keeps_order_and_multiline_body(self):
        text = "- 🤖 first\n- 🤖 second\ncontinued\n\n- 🤖 third\n"
        assert parse_prompts(text) == ["first", "second\ncontinued", "third"]

    def test_hand_typed_notes_after_a_prompt_are_not_swallowed(self):
        text = "- 🤖 only this\n\n=== a section of his own\n  some private line\n"
        assert parse_prompts(text) == ["only this"]

    def test_tolerates_variation_selector_and_spacing(self):
        assert parse_prompts("-   🤖️  spaced out  \n") == ["spaced out"]


class TestPromptsProbe:
    def test_probe_has_no_prompts_when_absent(self, tmp_path):
        assert _build_notes_summary_probe(tmp_path)["prompts_count"] == 0

    def test_probe_counts_prompts(self, tmp_path):
        _write_notes(tmp_path, "- 🤖 one\n- 📋 pasted\n- 🤖 two\n")
        assert _build_notes_summary_probe(tmp_path)["prompts_count"] == 2

    def test_broadcast_on_notes_change(self, tmp_path):
        _write_notes(tmp_path, "- 🤖 one\n")
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as bc:
            _broadcast_notes_summary_counts(probe, "notes", None)
        counts = [c.args[0] for c in bc.call_args_list
                  if isinstance(c.args[0], PromptsCountUpdatedMsg)]
        assert [m.count for m in counts] == [1]

    def test_silent_when_only_files_changed(self, tmp_path):
        _write_notes(tmp_path, "- 🤖 one\n")
        probe = _build_notes_summary_probe(tmp_path)
        with patch("daemon.ws_publish.broadcast") as bc:
            _broadcast_notes_summary_counts(probe, "files", None)
        assert not [c for c in bc.call_args_list
                    if isinstance(c.args[0], PromptsCountUpdatedMsg)]
