#!/usr/bin/env python3
"""Append periodic timestamp markers to a transcription file.

Default behavior is tuned for quick testing: one marker every 3 seconds.
Use --interval-seconds 60 for real workshop usage.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append timestamp marker lines to a transcription file on a fixed interval."
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
        help="Interval between markers in seconds (default: 3 for testing).",
    )
    parser.add_argument(
        "--speaker",
        default="Timestamp",
        help="Speaker label used in appended lines (default: Timestamp).",
    )
    parser.add_argument(
        "--label",
        default="[auto-marker]",
        help="Text label included in each appended marker line.",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Append this many markers then stop (useful for tests).",
    )
    return parser.parse_args()


def build_marker_line(now: datetime, speaker: str, label: str) -> str:
    ts = now.strftime("%H:%M:%S")
    # Match existing parser-friendly format: [HH:MM:SS.xx] Speaker:\ttext
    return f"[{ts}.00] {speaker}:\t{label} {now.strftime('%Y-%m-%d %H:%M:%S')}"


def append_marker(file_path: Path, speaker: str, label: str) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    line = build_marker_line(datetime.now(), speaker=speaker, label=label)
    with file_path.open("a", encoding="utf-8") as f:
        f.write("\n" + line)
        f.flush()
    return line


def run_loop(file_path: Path, interval_seconds: float, speaker: str, label: str, ticks: int | None = None) -> int:
    if interval_seconds <= 0:
        raise ValueError("interval-seconds must be > 0")

    stop = False

    def handle_stop(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    count = 0
    print(f"[info] Appending markers to: {file_path}")
    print(f"[info] Interval: {interval_seconds:.2f}s")
    print("[info] Press Ctrl+C to stop")

    while not stop:
        appended = append_marker(file_path, speaker=speaker, label=label)
        count += 1
        print(f"[{count}] {appended}")

        if ticks is not None and count >= ticks:
            break

        time.sleep(interval_seconds)

    print(f"[info] Stopped after {count} marker(s).")
    return count


def main() -> int:
    args = parse_args()

    try:
        run_loop(
            file_path=args.file,
            interval_seconds=args.interval_seconds,
            speaker=args.speaker,
            label=args.label,
            ticks=args.ticks,
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

