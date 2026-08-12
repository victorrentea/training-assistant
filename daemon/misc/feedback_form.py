"""Persistence for the end-of-session participant feedback form.

The published FOS form URL lives in the session folder rather than only in
memory: the daemon auto-restarts on every push to master, and an in-memory-only
URL would silently disappear from participant screens mid-session.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from daemon import log

FEEDBACK_FORM_FILE = "feedback-form.json"


def save_feedback_form(folder: Path, title: str, url: str) -> str:
    """Write the published form to the session folder. Returns the ISO created_at."""
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {"title": title, "url": url, "created_at": created_at}
    (folder / FEEDBACK_FORM_FILE).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return created_at


def load_feedback_form(folder: Path) -> dict | None:
    """Read the persisted form, or None if absent/unreadable."""
    path = folder / FEEDBACK_FORM_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("session", f"Unreadable {FEEDBACK_FORM_FILE}: {e}")
        return None
    if not isinstance(data, dict) or not data.get("url"):
        return None
    return {
        "title": data.get("title", ""),
        "url": data["url"],
        "created_at": data.get("created_at", ""),
    }
