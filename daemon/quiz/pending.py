"""Shared pending-request state for poll generation.

The host REST router writes into this dict; the main orchestrator loop reads from it.
"""
import threading

_lock = threading.Lock()

# Keys: "poll_request", "poll_refine"  — internal keys consumed by the main orchestrator loop
_pending: dict[str, dict] = {}


def put(key: str, value: dict) -> None:
    with _lock:
        _pending[key] = value


def pop(key: str) -> dict | None:
    with _lock:
        return _pending.pop(key, None)
