"""Query normalized transcript lines by time range.

Reads normalized files produced by `daemon.transcript_normalizer`:
  YYYY-MM-DD transcription.txt with lines like: [HH:MM] Speaker: text
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path

_NORMALIZED_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+transcription\.txt$", re.IGNORECASE)
_LINE_RE = re.compile(r"^\[(\d{2}):(\d{2})\]\s*(.*)$")
_DEFAULT_FOLDER = Path(os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/Documents/transcriptions"))


@dataclass
class QueryRange:
    start: datetime
    end: datetime


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    if "T" not in value:
        raise ValueError(f"Invalid datetime: {value}. Use ISO format: YYYY-MM-DDTHH:MM[:SS].")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {value}. Use ISO format: YYYY-MM-DDTHH:MM[:SS].") from exc


def _resolve_query_range(args: argparse.Namespace) -> QueryRange:
    start = _parse_datetime(args.from_iso)
    end = _parse_datetime(args.to_iso)
    if end <= start:
        raise ValueError("End must be after start")
    return QueryRange(start=start, end=end)


def _parse_line(line: str, day: date) -> tuple[datetime, str] | None:
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    payload = m.group(3).strip()
    dt = datetime.combine(day, time(hh, mm))
    return dt, payload


def load_normalized_entries(folder: Path, since_date: date | None = None) -> list[tuple[datetime, str]]:
    entries: list[tuple[datetime, str]] = []
    files = sorted(
        [f for f in folder.iterdir() if f.is_file() and _NORMALIZED_FILE_RE.match(f.name)],
        key=lambda p: p.name,
    )
    for file_path in files:
        m = _NORMALIZED_FILE_RE.match(file_path.name)
        if not m:
            continue
        day = date.fromisoformat(m.group(1))
        if since_date and day < since_date:
            continue
        for raw in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = _parse_line(raw, day)
            if parsed is not None:
                entries.append(parsed)
    return entries


def query_lines(folder: Path, query: QueryRange) -> list[str]:
    lines: list[str] = []
    for dt, payload in load_normalized_entries(folder, since_date=query.start.date()):
        if query.start <= dt <= query.end:
            lines.append(f"[{dt.strftime('%Y-%m-%d %H:%M')}] {payload}")
    return lines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query normalized transcript lines for an ISO time interval")
    parser.add_argument("from_iso", help="Start ISO datetime: YYYY-MM-DDTHH:MM[:SS]")
    parser.add_argument("to_iso", help="End ISO datetime: YYYY-MM-DDTHH:MM[:SS]")
    parser.add_argument("--folder", type=Path, default=_DEFAULT_FOLDER, help="Folder with normalized files")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.folder.exists() or not args.folder.is_dir():
        print(f"Folder not found: {args.folder}")
        return 2

    try:
        query = _resolve_query_range(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    lines = query_lines(args.folder, query)
    for line in lines:
        print(line)

    print(
        f"\n# range: {query.start.strftime('%Y-%m-%d %H:%M')} -> {query.end.strftime('%Y-%m-%d %H:%M')}"
        f" · lines: {len(lines)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
