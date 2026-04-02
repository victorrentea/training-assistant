"""Stub adapter — controllable implementations for Docker/Linux/CI environments.

Tests control the stub by writing JSON to well-known files:
  /tmp/stub-intellij.json    → {project, path, branch, frontmost}

The stub reads these files on each probe call. If the file doesn't exist
or is empty, the probe returns None (nothing running).

Used when DAEMON_ADAPTER=stub.
"""

import json
from pathlib import Path

from daemon import log

_INTELLIJ_STATE_FILE = Path("/tmp/stub-intellij.json")
_CALLS_LOG_FILE = Path("/tmp/stub-calls.jsonl")


def _log_call(fn_name: str, **kwargs) -> None:
    """Append a call record for test observability."""
    try:
        with open(_CALLS_LOG_FILE, "a") as f:
            f.write(json.dumps({"fn": fn_name, **kwargs}) + "\n")
    except Exception:
        pass


def probe_intellij(timeout: float = 2.0) -> dict | None:
    """Return state from /tmp/stub-intellij.json, or None if not set."""
    if not _INTELLIJ_STATE_FILE.exists():
        return None
    try:
        data = json.loads(_INTELLIJ_STATE_FILE.read_text())
        if not data or not data.get("project"):
            return None
        return {
            "project": data["project"],
            "path": data.get("path", ""),
            "branch": data.get("branch", "main"),
            "frontmost": data.get("frontmost", False),
        }
    except Exception:
        return None


def beep() -> None:
    """No-op."""
    _log_call("beep")


def is_google_drive_running() -> bool:
    """Always returns True (assume available)."""
    return True
