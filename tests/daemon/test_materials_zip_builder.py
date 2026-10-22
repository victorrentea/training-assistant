import io
import zipfile

import pytest

from daemon.materials.zip_builder import (
    MAX_ZIP_BYTES,
    ZipTooLargeError,
    build_session_zip,
    session_zip_filename,
)


def _entries(data: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return set(archive.namelist())


def _make_session(tmp_path):
    folder = tmp_path / "2026-07-27..29 Spring+Quarkus@DB"
    (folder / "wiki").mkdir(parents=True)
    (folder / ".obsidian").mkdir()
    (folder / "wiki" / "Dependency Injection.md").write_text("di", encoding="utf-8")
    (folder / "ai-summary.md").write_text("summary", encoding="utf-8")
    (folder / "Agenda.docx").write_bytes(b"docx")
    (folder / "opened-files.md").write_text("files", encoding="utf-8")
    (folder / "session-state.json").write_text("{}", encoding="utf-8")
    (folder / "attendees.md").write_text("names", encoding="utf-8")
    (folder / "Icon").write_bytes(b"")
    (folder / "~$Agenda.docx").write_bytes(b"lock")
    (folder / "wiki.zip").write_bytes(b"PK")
    (folder / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
    return folder


def test_includes_content_with_relative_arcnames(tmp_path):
    folder = _make_session(tmp_path)
    entries = _entries(build_session_zip(folder))
    assert entries == {
        "wiki/Dependency Injection.md",
        "ai-summary.md",
        "Agenda.docx",
        "opened-files.md",
    }


def test_excludes_internal_state_and_attendees(tmp_path):
    folder = _make_session(tmp_path)
    entries = _entries(build_session_zip(folder))
    assert "session-state.json" not in entries
    assert "attendees.md" not in entries


def test_excludes_junk_globs_and_obsidian_dir(tmp_path):
    folder = _make_session(tmp_path)
    entries = _entries(build_session_zip(folder))
    assert "Icon" not in entries
    assert "~$Agenda.docx" not in entries
    assert "wiki.zip" not in entries
    assert not any(entry.startswith(".obsidian/") for entry in entries)


def test_archive_content_round_trips(tmp_path):
    folder = _make_session(tmp_path)
    with zipfile.ZipFile(io.BytesIO(build_session_zip(folder))) as archive:
        assert archive.read("wiki/Dependency Injection.md") == b"di"


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_session_zip(tmp_path / "does-not-exist")


def test_size_guard_trips(tmp_path, monkeypatch):
    import daemon.materials.zip_builder as builder

    monkeypatch.setattr(builder, "MAX_ZIP_BYTES", 128)
    folder = tmp_path / "big"
    folder.mkdir()
    # Random-ish bytes so DEFLATE cannot squeeze it under the cap.
    (folder / "payload.bin").write_bytes(bytes(range(256)) * 64)
    with pytest.raises(ZipTooLargeError):
        builder.build_session_zip(folder)


def test_filename_is_folder_name(tmp_path):
    folder = _make_session(tmp_path)
    assert session_zip_filename(folder) == "2026-07-27..29 Spring+Quarkus@DB.zip"


def test_max_zip_bytes_is_25mb():
    assert MAX_ZIP_BYTES == 25 * 1024 * 1024
