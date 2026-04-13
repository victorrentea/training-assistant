#!/usr/bin/env python3
"""Resolve a local Google Drive folder path to its Google Drive web URL.

Usage: python3 scripts/resolve_gdrive_link.py <local_folder_path>
Prints the Google Drive URL to stdout, or exits with code 1 on failure.
"""
import sqlite3
import sys
from pathlib import Path


def find_drive_dbs() -> tuple[Path, Path] | None:
    """Find the DriveFS mirror and metadata SQLite databases."""
    base = Path.home() / "Library" / "Application Support" / "Google" / "DriveFS"
    if not base.exists():
        return None
    # Find the first account directory (numeric ID)
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and entry.name.isdigit():
            mirror = entry / "mirror_sqlite.db"
            meta = entry / "mirror_metadata_sqlite.db"
            if mirror.exists() and meta.exists():
                return mirror, meta
    return None


def resolve_gdrive_url(local_path: str) -> str | None:
    """Resolve a local Google Drive path to a Google Drive web URL."""
    dbs = find_drive_dbs()
    if not dbs:
        return None
    mirror_db, meta_db = dbs

    folder_name = Path(local_path).name

    # Step 1: find stable_id by folder name in mirror_item
    conn = sqlite3.connect(f"file:{mirror_db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT stable_id, local_filename FROM mirror_item WHERE local_filename = ?",
            (folder_name,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return None

    # If multiple matches, try to disambiguate by checking parent path
    stable_ids = [r[0] for r in rows]

    # Step 2: map stable_id → cloud_id via metadata DB
    conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in stable_ids)
        cloud_rows = conn.execute(
            f"SELECT stable_id, cloud_id FROM stable_ids WHERE stable_id IN ({placeholders})",
            stable_ids,
        ).fetchall()
    finally:
        conn.close()

    if not cloud_rows:
        return None

    # If single match, use it; if multiple, pick the last one (most recent stable_id)
    cloud_id = max(cloud_rows, key=lambda r: r[0])[1]
    return f"https://drive.google.com/drive/folders/{cloud_id}"


def gdrive_view_url_to_presentation_export_url(gdrive_url: str) -> str | None:
    """Convert a Drive file view URL to a Google Slides PDF export URL.

    Input:  https://drive.google.com/file/d/{ID}/view
    Output: https://docs.google.com/presentation/d/{ID}/export/pdf
    """
    import re
    m = re.search(r"/file/d/([^/]+)", gdrive_url)
    if m:
        return f"https://docs.google.com/presentation/d/{m.group(1)}/export/pdf"
    return None


def resolve_gdrive_file_url(local_path: str) -> str | None:
    """Resolve a local Google Drive file path to a Google Drive web URL (view link)."""
    dbs = find_drive_dbs()
    if not dbs:
        return None
    mirror_db, meta_db = dbs

    file_name = Path(local_path).name

    conn = sqlite3.connect(f"file:{mirror_db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT stable_id FROM mirror_item WHERE local_filename = ?",
            (file_name,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return None

    stable_ids = [r[0] for r in rows]

    conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in stable_ids)
        cloud_rows = conn.execute(
            f"SELECT stable_id, cloud_id FROM stable_ids WHERE stable_id IN ({placeholders})",
            stable_ids,
        ).fetchall()
    finally:
        conn.close()

    if not cloud_rows:
        return None

    cloud_id = max(cloud_rows, key=lambda r: r[0])[1]
    return f"https://drive.google.com/file/d/{cloud_id}/view"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/resolve_gdrive_link.py <local_folder_path>", file=sys.stderr)
        sys.exit(1)
    url = resolve_gdrive_url(sys.argv[1])
    if url:
        print(url)
    else:
        print(f"Could not resolve Google Drive link for: {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)
