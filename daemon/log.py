"""Shared log formatter for all training-assistant daemons.

Format: HH:MM:SS.f  PID  [name      ] info    message
        HH:MM:SS.f  PID  [name      ] error   message

Example:
    18:49:41.4 66405  [daemon    ] info    Started — polling https://...
    18:49:41.7 66405  [transcript] info    Mar 22 · 3127 lines
    18:49:41.7 66405  [session   ] error   Failed to load key points

Usage:
    from daemon import log
    log.info("daemon", "Started polling server")
    log.error("session", f"Failed to load: {e}")
"""

import os
import sys
from datetime import datetime

_PID = os.getpid()


def _ts() -> str:
    n = datetime.now()
    return n.strftime("%H:%M:%S") + "." + str(n.microsecond // 100000)


def _fmt(name: str, level: str, msg: str) -> str:
    nm = name[:10].ljust(10)
    # "info    " and "error   " both = 8 display cols → message column always aligned
    lvl = "error   " if level == "error" else "info    "
    return f"{_ts()} {_PID:5}  [{nm}] {lvl}{msg}"


def info(name: str, msg: str) -> None:
    print(_fmt(name, "info", msg), flush=True)


def error(name: str, msg: str) -> None:
    print(_fmt(name, "error", msg), file=sys.stderr, flush=True)
