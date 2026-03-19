#!/usr/bin/env python3
"""Append empty lines to a transcription file at a fixed interval.

Default behavior appends one blank line every 3 seconds for 3 minutes.
"""

from __future__ import annotations

import argparse
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_FIRST_LINE_PATTERN = re.compile(r"^(\[\s*)\d{2}:\d{2}:\d{2}\.\d+(\s*\]\s*).*$")


@dataclass(frozen=True)
class TimestampLineTemplate:
    open_prefix: str
    close_prefix: str


_DEFAULT_TEMPLATE = TimestampLineTemplate(
    open_prefix="[",
    close_prefix="] ",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append empty lines to a transcription file on a fixed interval."
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Path to the transcription text file.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=3.0,
        help="Interval between inserts in seconds (default: 3 for testing).",
    )
    parser.add_argument(
        "--run-minutes",
        type=float,
        default=3.0,
        help="How long to run before stopping (default: 3 minutes).",
    )
    return parser.parse_args()


def infer_template_from_first_line(file_path: Path) -> TimestampLineTemplate:
    if not file_path.exists():
        return _DEFAULT_TEMPLATE

    first_line = ""
    with file_path.open("r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline().rstrip("\r\n")

    m = _FIRST_LINE_PATTERN.match(first_line)
    if not m:
        return _DEFAULT_TEMPLATE

    return TimestampLineTemplate(
        open_prefix=m.group(1),
        close_prefix=m.group(2),
    )


def build_timestamp_line(now: datetime, template: TimestampLineTemplate) -> str:
    line = f"{template.open_prefix}{now.strftime('%H:%M:%S')}.00{template.close_prefix}"
    return line if line.endswith(" ") else f"{line} "



def append_empty_line_then_timestamp(file_path: Path, template: TimestampLineTemplate, now: datetime | None = None) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    line = build_timestamp_line(now or datetime.now(), template)
    separator = "\n"
    with file_path.open("a", encoding="utf-8") as f:
        f.write(separator)
        f.write(line)
        f.flush()
    return line


def run_loop(
    file_path: Path,
    interval_seconds: float,
    run_seconds: float | None = None,
) -> int:
    if interval_seconds <= 0:
        raise ValueError("interval-seconds must be > 0")
    if run_seconds is not None and run_seconds <= 0:
        raise ValueError("run duration must be > 0")

    stop = False

    def handle_stop(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    count = 0
    template = infer_template_from_first_line(file_path)
    deadline = time.monotonic() + run_seconds if run_seconds is not None else None
    print(f"[info] Appending lines to: {file_path}")
    print(f"[info] Interval: {interval_seconds:.2f}s")
    if run_seconds is None:
        print("[info] Press Ctrl+C to stop")
    else:
        print(f"[info] Run duration: {run_seconds:.1f}s")

    while not stop:
        append_empty_line_then_timestamp(file_path, template)
        count += 1

        now = time.monotonic()
        if deadline is not None and now >= deadline:
            break

        sleep_for = interval_seconds
        if deadline is not None:
            sleep_for = min(interval_seconds, max(0.0, deadline - now))
        if sleep_for <= 0:
            break
        time.sleep(sleep_for)

    print(f"[info] Stopped after {count} insert(s).")
    return count


def main() -> int:
    args = parse_args()

    try:
        run_loop(
            file_path=args.file,
            interval_seconds=args.interval_seconds,
            run_seconds=args.run_minutes * 60,
        )
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"[error] Could not write to file: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

