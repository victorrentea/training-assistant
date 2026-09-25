from pathlib import Path

from daemon.session_state import (
    TRANSCRIPTION_DISCLOSURE,
    create_notes_file,
)


def test_new_notes_file_has_name_then_transcription_disclosure(tmp_path: Path):
    folder = tmp_path / "2026-09-15 Clean Code"
    folder.mkdir()

    notes = create_notes_file(folder)

    lines = notes.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "2026-09-15 Clean Code - notes.txt",
        "⚠️ This meeting is transcribed using a local model on Victor's machine"
        " to generate a summary of the content at the end.",
    ]


def test_existing_notes_file_is_not_clobbered(tmp_path: Path):
    folder = tmp_path / "s"
    folder.mkdir()
    existing = folder / "s - notes.txt"
    existing.write_text("my notes\n", encoding="utf-8")

    assert create_notes_file(folder) == existing
    assert existing.read_text(encoding="utf-8") == "my notes\n"
