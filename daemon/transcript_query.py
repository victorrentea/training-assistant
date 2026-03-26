"""Query normalized transcript lines by time range.

Reads normalized files produced by `daemon.transcript_normalizer`:
  YYYY-MM-DD transcription.txt with lines like: [HH:MM] Speaker: text
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
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
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime: {value}. Use 'YYYY-MM-DD HH:MM' or ISO 'YYYY-MM-DDTHH:MM'.")


def _iter_days(start_day: date, end_day: date):
    day = start_day
    while day <= end_day:
        yield day
        day += timedelta(days=1)


def _resolve_query_range(args: argparse.Namespace, now: datetime) -> QueryRange:
    positional_mode = bool(getattr(args, "iso_range", None))
    selected = sum(
        1
        for flag in (
            positional_mode,
            bool(args.today),
            bool(args.yesterday_afternoon),
            args.last_minutes is not None,
            args.from_dt is not None or args.to_dt is not None,
        )
        if flag
    )
    if selected == 0:
        raise ValueError("Choose one mode: --today, --yesterday-afternoon, --last-minutes, or --from/--to.")
    if selected > 1:
        raise ValueError("Use only one mode at a time.")

    if positional_mode:
        if len(args.iso_range) != 2:
            raise ValueError("ISO positional mode requires exactly 2 args: <from_iso> <to_iso>")
        start = _parse_datetime(args.iso_range[0])
        end = _parse_datetime(args.iso_range[1])
        if end <= start:
            raise ValueError("End must be after start")
        return QueryRange(start=start, end=end)

    if args.today:
        start = datetime.combine(now.date(), time(0, 0))
        return QueryRange(start=start, end=now)

    if args.yesterday_afternoon:
        yday = now.date() - timedelta(days=1)
        start = datetime.combine(yday, time(12, 0))
        return QueryRange(start=start, end=now)

    if args.last_minutes is not None:
        if args.last_minutes <= 0:
            raise ValueError("--last-minutes must be > 0")
        start = now - timedelta(minutes=args.last_minutes)
        return QueryRange(start=start, end=now)

    if args.from_dt is None:
        raise ValueError("--from is required when using explicit range")
    start = _parse_datetime(args.from_dt)
    end = _parse_datetime(args.to_dt) if args.to_dt else now
    if end <= start:
        raise ValueError("End must be after start")
    return QueryRange(start=start, end=end)


def _normalized_file_for_day(folder: Path, day: date) -> Path:
    return folder / f"{day.isoformat()} transcription.txt"


def _parse_line(line: str, day: date) -> tuple[datetime, str] | None:
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    payload = m.group(3).strip()
    dt = datetime.combine(day, time(hh, mm))
    return dt, payload


def query_lines(folder: Path, query: QueryRange) -> list[str]:
    lines: list[str] = []
    for day in _iter_days(query.start.date(), query.end.date()):
        file_path = _normalized_file_for_day(folder, day)
        if not file_path.exists() or not file_path.is_file():
            continue
        raw_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for raw in raw_lines:
            parsed = _parse_line(raw, day)
            if parsed is None:
                continue
            dt, payload = parsed
            if query.start <= dt <= query.end:
                lines.append(f"[{dt.strftime('%Y-%m-%d %H:%M')}] {payload}")
    return lines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query normalized transcript lines by time range")
    parser.add_argument(
        "iso_range",
        nargs="*",
        help="Optional positional range: <from_iso> <to_iso> (example: 2026-03-25T17:00:00 2026-03-26T08:23:12)",
    )
    parser.add_argument("--folder", type=Path, default=_DEFAULT_FOLDER, help="Folder with normalized files")

    mode = parser.add_argument_group("Modes (pick one)")
    mode.add_argument("--today", action="store_true", help="From today's 00:00 until now")
    mode.add_argument(
        "--yesterday-afternoon",
        action="store_true",
        dest="yesterday_afternoon",
        help="From yesterday 12:00 until now",
    )
    mode.add_argument("--last-minutes", type=int, help="From now-N-minutes until now")
    mode.add_argument("--from", dest="from_dt", help="Start datetime: YYYY-MM-DD HH:MM")
    mode.add_argument("--to", dest="to_dt", help="End datetime: YYYY-MM-DD HH:MM (default: now)")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.folder.exists() or not args.folder.is_dir():
        print(f"Folder not found: {args.folder}")
        return 2

    now = datetime.now()
    try:
        query = _resolve_query_range(args, now)
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
