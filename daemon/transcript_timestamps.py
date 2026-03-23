"""Transcript timestamp heartbeat helpers used by the local quiz daemon."""

from __future__ import annotations

import re
import signal
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_FIRST_LINE_PATTERN = re.compile(r"^(\[\s*)(?:\d{4}-\d{2}-\d{2}\s+)?\d{2}:\d{2}:\d{2}\.\d+(\s*\]\s*).*$")


@dataclass(frozen=True)
class TimestampLineTemplate:
    open_prefix: str
    close_prefix: str


_DEFAULT_TEMPLATE = TimestampLineTemplate(
    open_prefix="[",
    close_prefix="] ",
)


def infer_template_from_first_line(file_path: Path) -> TimestampLineTemplate:
    if not file_path.exists():
        return _DEFAULT_TEMPLATE

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
    line = f"{template.open_prefix}{now.strftime('%Y-%m-%d %H:%M:%S')}.00{template.close_prefix}"
    return line if line.endswith(" ") else f"{line} "


def append_empty_line_then_timestamp(
    file_path: Path,
    template: TimestampLineTemplate,
    now: datetime | None = None,
) -> str:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    line = build_timestamp_line(now or datetime.now(), template)
    with file_path.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.write(line)
        f.flush()
    return line


def run_loop(
    file_path: Path,
    interval_seconds: float,
    run_seconds: float | None = None,
) -> int:
    """Utility loop used by tests to validate periodic appending behavior."""
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

