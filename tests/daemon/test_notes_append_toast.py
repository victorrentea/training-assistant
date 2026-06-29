"""Unit tests for the notes-append toast delta logic.

The daemon's only signal that text was shared with participants is the notes
file changing on disk (the macOS addon writes notes.txt directly). These tests
pin the pure decision function that turns a before/after probe into the snippet
to toast — and the cases that must stay silent (edits, rewrites, undo, session
switch, initial probe).
"""
from daemon.__main__ import _extract_appended_snippet, _notes_append_snippet

NOTES = "/sessions/Demo/Demo - notes.txt"


def _probe(text, notes_file=NOTES):
    return {"notes_file": notes_file, "notes_text": text}


def _append(prev_text, curr_text, change_parts="notes", prev_file=NOTES, curr_file=NOTES):
    return _notes_append_snippet(_probe(prev_text, prev_file), _probe(curr_text, curr_file), change_parts)


class TestExtractAppendedSnippet:
    def test_strips_bullet_and_trims(self):
        assert _extract_appended_snippet("\n- https://example.com\n") == "https://example.com"

    def test_plain_line_without_bullet(self):
        assert _extract_appended_snippet("\nhello world\n") == "hello world"

    def test_multiline_entry_preserves_internal_newlines(self):
        assert _extract_appended_snippet("\n- line1\nline2\n") == "line1\nline2"

    def test_empty_delta_yields_empty(self):
        assert _extract_appended_snippet("\n- \n") == ""


class TestNotesAppendSnippet:
    def test_pure_append_toasts_clean_snippet(self):
        prev = "Demo - notes.txt\n"
        curr = prev + "- https://example.com/x\n"
        assert _append(prev, curr) == "https://example.com/x"

    def test_multiline_append_is_one_snippet(self):
        prev = "header\n"
        curr = prev + "- first\nsecond\n"
        assert _append(prev, curr) == "first\nsecond"

    def test_edit_not_an_append_is_silent(self):
        # Content changed but does not extend the previous text.
        assert _append("aaa\nbbb\n", "aaa\nCCC\n") is None

    def test_undo_truncation_is_silent(self):
        prev = "header\n- shared\n"
        curr = "header\n"  # file shrank (addon hover-to-undo)
        assert _append(prev, curr) is None

    def test_initial_probe_no_previous_is_silent(self):
        assert _notes_append_snippet(None, _probe("header\n- x\n"), "initial") is None

    def test_empty_previous_first_write_is_silent(self):
        # New notes file: only the self-labeling first line exists, no real append yet.
        assert _append("", "Demo - notes.txt\n") is None

    def test_session_switch_different_file_is_silent(self):
        prev = "Old - notes.txt\n"
        curr = prev + "- x\n"
        assert _append(prev, curr, prev_file="/a/Old.txt", curr_file="/b/New.txt") is None

    def test_change_without_notes_part_is_silent(self):
        prev = "header\n"
        curr = prev + "- x\n"
        assert _append(prev, curr, change_parts="summary") is None
