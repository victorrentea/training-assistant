"""Shared session state accessible from the daemon session router.

The main orchestrator loop (`daemon/__main__.py`) updates these fields;
the session router reads them to serve the GET /api/session/active and
GET /api/session/folders endpoints.
"""
import threading
from pathlib import Path

_lock = threading.Lock()

# Set by daemon/__main__.py after initialization
_session_stack: list[dict] = []   # reference to the live session stack (shallow copy on read)
_active_session_id: str | None = None
_sessions_root: Path | None = None


def set_active_session(session_id: str | None, stack: list[dict]) -> None:
    """Called by main loop whenever session stack or active_session_id changes."""
    global _active_session_id, _session_stack
    with _lock:
        _active_session_id = session_id
        _session_stack = list(stack)  # snapshot copy


def set_sessions_root(root: Path) -> None:
    """Called by main loop at startup with the resolved sessions root path."""
    global _sessions_root
    with _lock:
        _sessions_root = root


def get_active_session_id() -> str | None:
    with _lock:
        return _active_session_id


def get_session_stack() -> list[dict]:
    with _lock:
        return list(_session_stack)


def get_sessions_root() -> Path | None:
    with _lock:
        return _sessions_root
