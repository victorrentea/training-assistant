"""Stub adapter — controllable implementations for Docker/Linux/CI environments.

Used when DAEMON_ADAPTER=stub.
"""

import json
from pathlib import Path

_CALLS_LOG_FILE = Path("/tmp/stub-calls.jsonl")


def _log_call(fn_name: str, **kwargs) -> None:
    """Append a call record for test observability."""
    try:
        with open(_CALLS_LOG_FILE, "a") as f:
            f.write(json.dumps({"fn": fn_name, **kwargs}) + "\n")
    except Exception:
        pass


def beep() -> None:
    """No-op."""
    _log_call("beep")


def open_in_vscode(path) -> None:
    """No-op (records the call for test observability)."""
    _log_call("open_in_vscode", path=str(path))


def is_google_drive_running() -> bool:
    """Always returns True (assume available)."""
    return True
