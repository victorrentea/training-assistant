"""Shared log formatter for all training-assistant daemons.

Format: [name-PID        ] HH:MM:SS.f info    message
        [name-PID        ] HH:MM:SS.f error❌ message

Usage:
    from daemon import log
    log.info("daemon", "Started polling server")
    log.error("session", f"Failed to load: {e}")
"""

import os
import sys
from datetime import datetime

# label = "name-PID", padded to this width inside brackets
# max: "summarizer-99999" = 16 chars
_LABEL_WIDTH = 16
_PID = os.getpid()


def _ts() -> str:
    n = datetime.now()
    return n.strftime("%H:%M:%S") + "." + str(n.microsecond // 100000)


def _fmt(name: str, level: str, msg: str) -> str:
    label = f"{name[:10]}-{_PID}".ljust(_LABEL_WIDTH)
    # "info   " = 7 display cols; "error❌" = 5 + 2-wide emoji = 7 display cols
    lvl = "error❌" if level == "error" else "info   "
    return f"[{label}] {_ts()} {lvl} {msg}"


def info(name: str, msg: str) -> None:
    print(_fmt(name, "info", msg), flush=True)


def error(name: str, msg: str) -> None:
    print(_fmt(name, "error", msg), file=sys.stderr, flush=True)
