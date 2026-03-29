"""PID lock file management for the training daemon."""

import json
import os
import signal
import sys
import time
from pathlib import Path

from daemon import log

_LOCK_FILE = Path("/tmp/training_daemon.lock")
_HEARTBEAT_INTERVAL = float(os.environ.get("DAEMON_HEARTBEAT_INTERVAL_SECONDS", "1.0"))  # seconds between heartbeat writes
_HEARTBEAT_STALE_THRESHOLD = 10.0  # seconds before heartbeat is considered stale


def read_lock() -> tuple[int | None, float | None]:
    """Read PID and last heartbeat from lock file. Returns (None, None) if missing/corrupt."""
    if not _LOCK_FILE.exists():
        return None, None
    try:
        data = json.loads(_LOCK_FILE.read_text())
        return int(data["pid"]), float(data["heartbeat"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None, None


def write_lock() -> None:
    """Write current PID and heartbeat timestamp to lock file."""
    _LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "heartbeat": time.time()}))


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)  # signal 0 = check existence only
        return True
    except (ProcessLookupError, PermissionError):
        return False


def check_and_acquire_lock() -> None:
    """Check lock file and decide whether to start, kill previous, or abort."""
    pid, heartbeat = read_lock()

    if pid is None:
        # No lock file or corrupt — safe to start
        return

    if pid == os.getpid():
        return

    alive = _is_process_alive(pid)
    heartbeat_age = time.time() - heartbeat if heartbeat else float("inf")

    if alive and heartbeat_age <= _HEARTBEAT_STALE_THRESHOLD:
        # Previous instance is healthy — abort
        log.info("daemon", f"Another instance is already running (PID {pid}, heartbeat {heartbeat_age:.1f}s ago). Exiting.")
        sys.exit(0)

    if alive and heartbeat_age > _HEARTBEAT_STALE_THRESHOLD:
        # Process exists but heartbeat is stale — something is wrong
        log.error("daemon", f"Previous instance (PID {pid}) is alive but heartbeat is stale ({heartbeat_age:.0f}s ago). Killing it.")
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except (ProcessLookupError, PermissionError):
            pass

    if not alive:
        # Process is dead — stale lock file from a crash
        log.info("daemon", f"Previous instance (PID {pid}) is dead (crashed?). Cleaning up lock file.")

    _LOCK_FILE.unlink(missing_ok=True)


def cleanup_lock(*_) -> None:
    """Remove lock file and exit. Suitable for use as a signal handler."""
    _LOCK_FILE.unlink(missing_ok=True)
    sys.exit(0)


def install_signal_handlers() -> None:
    """Install SIGTERM and SIGINT handlers to clean up lock on exit."""
    signal.signal(signal.SIGTERM, cleanup_lock)
    signal.signal(signal.SIGINT, cleanup_lock)
