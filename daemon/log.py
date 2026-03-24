"""Shared log formatter for all training-assistant daemons.

Format: [name      ] HH:MM:SS.f info    message
        [name      ] HH:MM:SS.f error❌ message

Usage:
    from daemon import log
    log.info("daemon", "Started polling server")
    log.error("session", f"Failed to load: {e}")
"""

import sys
from datetime import datetime

# Name is padded to this width inside brackets → [name      ] = 12 chars total
_MAX_NAME = 10


def _ts() -> str:
    n = datetime.now()
    return n.strftime("%H:%M:%S") + "." + str(n.microsecond // 100000)


def _fmt(name: str, level: str, msg: str) -> str:
    pad = name[:_MAX_NAME].ljust(_MAX_NAME)
    # "info   " = 7 display cols; "error❌" = 5 + 2-wide emoji = 7 display cols
    lvl = "error❌" if level == "error" else "info   "
    return f"[{pad}] {_ts()} {lvl} {msg}"


def info(name: str, msg: str) -> None:
    print(_fmt(name, "info", msg), flush=True)


def error(name: str, msg: str) -> None:
    print(_fmt(name, "error", msg), file=sys.stderr, flush=True)
