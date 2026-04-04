"""Shared pending-request state for session management.

The host REST router writes into this dict; the main orchestrator loop reads from it.
Mirrors the pattern used by daemon/quiz/pending.py.
"""
import threading

_lock = threading.Lock()

# Key: "session_request" — mirrors the WS message type used previously
_pending: dict[str, dict] = {}


def put(key: str, value: dict) -> None:
    with _lock:
        _pending[key] = value


def pop(key: str) -> dict | None:
    with _lock:
        return _pending.pop(key, None)
