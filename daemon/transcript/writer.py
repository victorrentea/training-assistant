"""Transcript output file writing helpers.

Handles appending normalized lines to per-day files and inferring speaker context
from already-written normalized output.
"""

from __future__ import annotations

import re
from pathlib import Path


def _append_outputs(output_dir: Path, grouped_lines: dict[str, list[str]]) -> list[Path]:
    written_files: list[Path] = []
    for day_str in sorted(grouped_lines.keys()):
        lines = grouped_lines[day_str]
        if not lines:
            continue
        out = output_dir / f"{day_str} transcription.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                f.write("\n")
        written_files.append(out)
    return written_files


def _infer_last_speaker_from_normalized(output_file: Path) -> str | None:
    if not output_file.exists():
        return None
    speaker_re = re.compile(r"^\[\d{2}:\d{2}\]\s+([^:]+):\s+")
    try:
        with output_file.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        m = speaker_re.match(line.strip())
        if m:
            return m.group(1).strip()
    return None
