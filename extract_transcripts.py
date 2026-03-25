#!/usr/bin/env python3
"""Extract transcript entries between two ISO datetime boundaries."""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from daemon.session_transcript import parse_txt_entries_with_datetimes
from quiz_core import _FILENAME_DATE_RE, _parse_srt, _parse_txt, _parse_vtt, load_secrets_env

_SUPPORTED_EXTENSIONS = {".txt", ".vtt", ".srt"}
_FULL_DATETIME_LINE_RE = re.compile(r"^\[\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s*\]", re.MULTILINE)
_SPEAKER_PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*")
_DEFAULT_TRANSCRIPTION_FOLDER = "/Users/victorrentea/Documents/transcriptions"


def parse_iso_local(value: str) -> datetime:
    """Parse ISO datetime without timezone (e.g. 2026-03-25T10:00)."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {value}") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"Timezone offsets are not supported: {value}")
    return parsed


def _sort_key(path: Path) -> str:
    """Keep the same ordering strategy as load_transcription_files()."""
    match = _FILENAME_DATE_RE.match(path.name)
    if match:
        return match.group(1) + match.group(2)
    return str(path.stat().st_mtime)


def _file_date(path: Path) -> date | None:
    match = _FILENAME_DATE_RE.match(path.name)
    if not match:
        return None
    ds = match.group(1)
    try:
        return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
    except ValueError:
        return None


def _resolve_file_date(path: Path) -> date:
    explicit = _file_date(path)
    if explicit is not None:
        return explicit
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def _session_start_seconds(path: Path) -> int | None:
    match = _FILENAME_DATE_RE.match(path.name)
    if not match:
        return None
    try:
        h = int(match.group(2)[:2])
        m = int(match.group(2)[2:4])
        return h * 3600 + m * 60
    except (ValueError, IndexError):
        return None


def _parse_txt_file(path: Path, raw: str) -> list[tuple[datetime, str]]:
    file_day = _resolve_file_date(path)

    if _FULL_DATETIME_LINE_RE.search(raw):
        parsed = parse_txt_entries_with_datetimes(raw, file_date=file_day)
        out: list[tuple[datetime, str]] = []
        for dt, text_value in parsed:
            if dt is None:
                continue
            normalized = text_value.replace("\t", " ").strip()
            if normalized:
                out.append((dt, normalized))
        return out

    parsed = _parse_txt(raw, session_start_secs=_session_start_seconds(path))
    base = datetime.combine(file_day, time.min)
    out: list[tuple[datetime, str]] = []
    for ts, text_value in parsed:
        if ts is None:
            continue
        normalized = text_value.strip()
        if normalized:
            out.append((base + timedelta(seconds=float(ts)), normalized))
    return out


def _parse_non_txt_file(path: Path, raw: str) -> list[tuple[datetime, str]]:
    parser = _parse_vtt if path.suffix.lower() == ".vtt" else _parse_srt
    file_day = _resolve_file_date(path)
    base = datetime.combine(file_day, time.min)
    out: list[tuple[datetime, str]] = []
    for ts, text_value in parser(raw):
        normalized = text_value.strip()
        if normalized:
            out.append((base + timedelta(seconds=float(ts)), normalized))
    return out


def extract_entries(folder: Path, start: datetime, end: datetime) -> list[tuple[datetime, str]]:
    """Return timestamped transcript entries inside [start, end]."""
    if end < start:
        raise ValueError("End datetime must be greater than or equal to start datetime")

    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Transcription folder not found: {folder}")

    files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in _SUPPORTED_EXTENSIONS],
        key=_sort_key,
    )

    # Keep a small safety margin around the requested interval for midnight overflows.
    min_day = start.date() - timedelta(days=1)
    max_day = end.date() + timedelta(days=1)

    selected: list[tuple[datetime, str]] = []
    for path in files:
        fd = _file_date(path)
        if fd is not None and (fd < min_day or fd > max_day):
            continue

        raw = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".txt":
            entries = _parse_txt_file(path, raw)
        else:
            entries = _parse_non_txt_file(path, raw)

        for dt, text_value in entries:
            if start <= dt <= end:
                selected.append((dt, text_value))

    selected.sort(key=lambda item: item[0])
    return selected


def format_entry(dt: datetime, text_value: str) -> str:
    return f"{dt.strftime('%Y-%m-%dT%H:%M')} {text_value}"


def _format_duration(start: datetime, end: datetime) -> str:
    total_minutes = int((end - start).total_seconds()) // 60
    if total_minutes <= 0:
        return "0m"
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _line_label(count: int) -> str:
    return "line" if count == 1 else "lines"


def format_summary_line(entries: list[tuple[datetime, str]], start: datetime, end: datetime) -> str:
    counts: dict[str, int] = {}
    for _, text_value in entries:
        match = _SPEAKER_PREFIX_RE.match(text_value.strip())
        speaker = match.group(1).strip() if match else "unknown"
        counts[speaker] = counts.get(speaker, 0) + 1

    duration = _format_duration(start, end)
    if not counts:
        return f"0 lines over {duration}"

    parts = [f"[{speaker}] {count} {_line_label(count)}" for speaker, count in counts.items()]
    return f"{', '.join(parts)} over {duration}"


def main(argv: list[str]) -> int:
    if len(argv) not in {3, 4}:
        print(
            "Usage: ./extract-transcripts.sh START_ISO END_ISO [TRANSCRIPTION_FOLDER]"
            "\nExample: ./extract-transcripts.sh 2026-03-25T10:00 2026-03-25T18:00",
            file=sys.stderr,
        )
        return 1

    start_raw, end_raw = argv[1], argv[2]

    try:
        start = parse_iso_local(start_raw)
        end = parse_iso_local(end_raw)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    load_secrets_env()
    folder = Path(argv[3]) if len(argv) == 4 else Path(
        os.environ.get("TRANSCRIPTION_FOLDER", _DEFAULT_TRANSCRIPTION_FOLDER)
    )

    try:
        entries = extract_entries(folder, start, end)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(format_summary_line(entries, start, end))
    for dt, text_value in entries:
        print(format_entry(dt, text_value))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
