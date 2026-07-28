"""Build a downloadable zip of the current session folder.

This is NOT the MaterialsMirrorRunner removed in dc1228ea: nothing is synced
in the background, there are no per-file endpoints, and `materials/` is never
touched. One on-demand archive of the session folder, built when a
participant asks for it.
"""
from __future__ import annotations

import fnmatch
import io
import zipfile
from pathlib import Path

MAX_ZIP_BYTES = 25 * 1024 * 1024

# "Icon\r" is the real name of the macOS custom-folder-icon file; Finder and
# `ls` both render it as "Icon".
EXCLUDED_NAMES = frozenset({"session-state.json", "attendees.md", "Icon", "Icon\r"})
EXCLUDED_GLOBS = ("~$*", "*.zip")
EXCLUDED_DIRS = frozenset({".obsidian"})


class ZipTooLargeError(RuntimeError):
    """The built archive exceeds MAX_ZIP_BYTES."""


def _is_excluded_name(name: str) -> bool:
    if name in EXCLUDED_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_GLOBS)


def build_session_zip(session_folder: Path) -> bytes:
    """Return a DEFLATE archive of session_folder, minus the exclusion set.

    Raises FileNotFoundError if the folder is missing, ZipTooLargeError if the
    result exceeds MAX_ZIP_BYTES.
    """
    if not session_folder.is_dir():
        raise FileNotFoundError(f"Session folder not found: {session_folder}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(session_folder.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(session_folder)
            if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
                continue
            if _is_excluded_name(path.name):
                continue
            archive.write(path, arcname=str(relative))

    data = buffer.getvalue()
    if len(data) > MAX_ZIP_BYTES:
        raise ZipTooLargeError(
            f"Session zip is {len(data) / 1024 / 1024:.1f} MB "
            f"(limit {MAX_ZIP_BYTES // 1024 // 1024} MB)"
        )
    return data


def session_zip_filename(session_folder: Path) -> str:
    """Participant-facing filename, e.g. '2026-07-27..29 Spring+Quarkus@DB.zip'."""
    return f"{session_folder.name}.zip"
