"""Shared session state accessible from the daemon session router.

The main orchestrator loop (`daemon/__main__.py`) updates these fields;
the session router reads them to serve the GET /api/session/active and
GET /api/session/folders endpoints.
"""
import threading
from pathlib import Path

_lock = threading.Lock()

_active_session_id: str | None = None
_active_session_name: str | None = None  # folder name of active session
_sessions_root: Path | None = None


def set_active_session(session_id: str | None, session_name: str | None) -> None:
    """Called by main loop whenever active session changes."""
    global _active_session_id, _active_session_name
    with _lock:
        _active_session_id = session_id
        _active_session_name = session_name


def set_sessions_root(root: Path) -> None:
    """Called by main loop at startup with the resolved sessions root path."""
    global _sessions_root
    with _lock:
        _sessions_root = root


def get_active_session_id() -> str | None:
    with _lock:
        return _active_session_id


def get_active_session_name() -> str | None:
    with _lock:
        return _active_session_name


def get_sessions_root() -> Path | None:
    with _lock:
        return _sessions_root
