"""Reset normalizer state and rebuild normalized transcripts from raw files.

This utility is intentionally explicit/destructive and creates a backup folder first.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from daemon.transcript.normalizer import normalize_incremental, is_raw_transcript_txt

_NORMALIZED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+transcription\.txt$", re.IGNORECASE)


def _default_folder() -> Path:
    return Path(os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/Documents/transcriptions"))


def _backup_folder(base: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return base / f".backup-normalized-{stamp}"


def _raw_sort_key(path: Path) -> tuple[str, float]:
    m = re.match(r"^(\d{8})\s+(\d{4})\b", path.name)
    if m:
        return (m.group(1) + m.group(2), path.stat().st_mtime)
    return ("", path.stat().st_mtime)


def rebuild(folder: Path, from_iso: str | None = None) -> int:
    if not folder.exists() or not folder.is_dir():
        print(f"Folder not found: {folder}")
        return 2

    if from_iso:
        try:
            datetime.fromisoformat(from_iso)
        except ValueError:
            print(f"Invalid --from-iso: {from_iso}. Use ISO datetime, e.g. 2026-03-24T09:30:00")
            return 2

    raw_files = sorted([p for p in folder.iterdir() if is_raw_transcript_txt(p)], key=_raw_sort_key)
    normalized_files = sorted([p for p in folder.iterdir() if p.is_file() and _NORMALIZED_RE.match(p.name)])
    legacy_offsets = sorted([p for p in folder.iterdir() if p.is_file() and p.name.endswith(".txt.offset")])
    shared_offsets = [p for p in [folder / "normalization.offset.txt", folder / "normalization.offset"] if p.exists()]

    if not raw_files:
        print("No raw transcript files found.")
        return 1

    backup_dir = _backup_folder(folder)
    backup_dir.mkdir(parents=True, exist_ok=False)

    to_backup = normalized_files + legacy_offsets + shared_offsets
    for src in to_backup:
        shutil.copy2(src, backup_dir / src.name)

    for f in normalized_files:
        f.unlink(missing_ok=True)
    for f in legacy_offsets:
        f.unlink(missing_ok=True)
    for f in shared_offsets:
        f.unlink(missing_ok=True)

    written_total = 0
    output_files = set()
    for raw in raw_files:
        # Use current timestamping behavior from existing normalizer implementation.
        res = normalize_incremental(raw)
        written_total += res.written_lines
        for out in res.output_files:
            output_files.add(str(out))

    print(f"Backup folder: {backup_dir}")
    if from_iso:
        print(f"Requested reset anchor: {from_iso}")
    print(f"Raw files processed: {len(raw_files)}")
    print(f"Normalized files generated: {len(output_files)}")
    print(f"Normalized lines written: {written_total}")
    print("Done.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset offsets and rebuild normalized transcripts")
    parser.add_argument("--folder", type=Path, default=_default_folder(), help="Transcript folder")
    parser.add_argument(
        "--from-iso",
        help="Requested reset anchor (ISO). Informational/audit field for this rebuild run.",
    )
    args = parser.parse_args()
    return rebuild(args.folder, args.from_iso)


if __name__ == "__main__":
    raise SystemExit(main())
