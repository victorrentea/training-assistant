"""Shared log formatter for all training-assistant daemons.

Format: HH:MM:SS.f PID [name___] info message
        HH:MM:SS.f PID [name___] error message
        HH:MM:SS.f PID [name___] debug message  ← only when DAEMON_DEBUG=1

Example:
    18:49:41.4 66405 [daemon ] info Started — polling https://...
    18:49:41.7 66405 [ws-clie] info Connected to wss://...
    18:49:41.7 66405 [session] error Failed to load key points

Usage:
    from daemon import log
    log.info("daemon", "Started polling server")
    log.error("session", f"Failed to load: {e}")
    log.debug("ppt", "Slide +1s: CleanCode.pptx #42")  # only prints when DAEMON_DEBUG=1
"""

import os
import re
import sys
import threading
from datetime import datetime
from typing import Literal

_PID = os.getpid()
_level_lock = threading.Lock()
_output_lock = threading.Lock()
_level = "info"
_ANSI_RESET = "\033[0m"
_ANSI_RED = "\033[31m"
_ANSI_LIGHT_GRAY = "\033[37m"
_PROGRESS_RE = re.compile(r"\+\d+s: .* \(total:\s*\d+s\)\s*$")
_progress_active = False
_progress_len = 0


def _ts() -> str:
    n = datetime.now()
    return n.strftime("%H:%M:%S") + "." + str(n.microsecond // 100000)


def _fmt(name: str, level: str, msg: str) -> str:
    nm = (str(name or "").strip() or "?")[:7].ljust(7)
    raw_level = str(level or "").strip().lower() or "info"
    if raw_level in {"info", "error", "debug"}:
        lvl = raw_level.ljust(5)
    else:
        lvl = raw_level[:5].ljust(5)
    return f"{_ts()} {_PID} [{nm}] {lvl} {msg}"


def _colorize(line: str, level: str, stream) -> str:
    force_color = os.environ.get("FORCE_COLOR", "").strip().lower() in {"1", "true", "yes", "on"}
    if not force_color and (not hasattr(stream, "isatty") or not stream.isatty()):
        return line
    if os.environ.get("NO_COLOR"):
        return line
    if level == "error":
        return f"{_ANSI_RED}{line}{_ANSI_RESET}"
    if level == "debug":
        return f"{_ANSI_LIGHT_GRAY}{line}{_ANSI_RESET}"
    return line


def get_level() -> Literal["info", "debug"]:
    with _level_lock:
        return _level  # type: ignore[return-value]


def set_level(level: str) -> str:
    normalized = str(level or "").strip().lower()
    if normalized not in {"info", "debug"}:
        raise ValueError("log level must be 'info' or 'debug'")
    global _level
    with _level_lock:
        _level = normalized
        return _level


def _flush_progress_line_if_needed() -> None:
    global _progress_active, _progress_len
    if not _progress_active:
        return
    sys.stdout.write("\n")
    sys.stdout.flush()
    _progress_active = False
    _progress_len = 0


def _is_progress_update(msg: str) -> bool:
    return bool(_PROGRESS_RE.search(str(msg or "").strip()))


def info(name: str, msg: str) -> None:
    line = _fmt(name, "info", msg)
    with _output_lock:
        global _progress_active, _progress_len
        if _is_progress_update(msg):
            colorized = _colorize(line, "info", sys.stdout)
            pad = ""
            if _progress_active and len(line) < _progress_len:
                pad = " " * (_progress_len - len(line))
            sys.stdout.write("\r" + colorized + pad)
            sys.stdout.flush()
            _progress_active = True
            _progress_len = len(line)
            return
        _flush_progress_line_if_needed()
        print(_colorize(line, "info", sys.stdout), flush=True)


def error(name: str, msg: str) -> None:
    line = _fmt(name, "error", msg)
    with _output_lock:
        _flush_progress_line_if_needed()
        print(_colorize(line, "error", sys.stderr), file=sys.stderr, flush=True)


def debug(name: str, msg: str) -> None:
    if get_level() == "debug":
        line = _fmt(name, "debug", msg)
        with _output_lock:
            _flush_progress_line_if_needed()
            print(_colorize(line, "debug", sys.stdout), flush=True)
