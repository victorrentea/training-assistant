"""Tests for auto-created session notes file (create_notes_file)."""

from daemon.session_state import create_notes_file, find_notes_in_folder


def test_create_notes_file_uses_folder_name(tmp_path):
    folder = tmp_path / "2026-06-05 AI@Acme#1"
    folder.mkdir()

    notes = create_notes_file(folder)

    assert notes.name == "2026-06-05 AI@Acme#1 - notes.txt"
    assert notes.exists()
    # First line is the file's own name (self-labelling header).
    assert notes.read_text(encoding="utf-8") == "2026-06-05 AI@Acme#1 - notes.txt\n"


def test_created_notes_file_is_discovered(tmp_path):
    folder = tmp_path / "2026-06-05 AI@Acme#1"
    folder.mkdir()
    assert find_notes_in_folder(folder) is None

    notes = create_notes_file(folder)

    assert find_notes_in_folder(folder) == notes


def test_create_notes_file_never_clobbers_existing(tmp_path):
    folder = tmp_path / "2026-06-05 AI@Acme#1"
    folder.mkdir()
    notes = create_notes_file(folder)
    notes.write_text("trainer typed this", encoding="utf-8")

    again = create_notes_file(folder)

    assert again == notes
    assert again.read_text(encoding="utf-8") == "trainer typed this"
