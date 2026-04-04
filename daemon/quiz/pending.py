"""Shared pending-request state for quiz generation.

The host REST router writes into this dict; the main orchestrator loop reads from it.
"""
import threading

_lock = threading.Lock()

# Keys: "quiz_request", "quiz_refine"  — mirrors the WS message types used previously
_pending: dict[str, dict] = {}


def put(key: str, value: dict) -> None:
    with _lock:
        _pending[key] = value


def pop(key: str) -> dict | None:
    with _lock:
        return _pending.pop(key, None)
