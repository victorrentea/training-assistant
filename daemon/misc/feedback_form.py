"""Persistence for the end-of-session participant feedback form.

The published FOS form URL lives in the session folder rather than only in
memory: the daemon auto-restarts on every push to master, and an in-memory-only
URL would silently disappear from participant screens mid-session.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import HttpUrl, TypeAdapter, ValidationError

from daemon import log

FEEDBACK_FORM_FILE = "feedback-form.json"

#: The same standard the POST endpoint holds its callers to (see
#: ``FeedbackFormRequest.url``). The file feeds exactly the same variable — the
#: one the participant page assigns to ``nav.href`` — so a hand-edited or
#: half-written marker must not smuggle in what the endpoint would have refused.
_URL_VALIDATOR = TypeAdapter(HttpUrl)


def save_feedback_form(folder: Path, title: str, url: str) -> str:
    """Write the published form to the session folder. Returns the ISO created_at."""
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {"title": title, "url": url, "created_at": created_at}
    (folder / FEEDBACK_FORM_FILE).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return created_at


def clear_feedback_form(folder: Path) -> bool:
    """Retract the published form. Returns True if a form was actually removed.

    Deletes the marker rather than blanking it: the boot-time restore keys off
    the file's existence, so a leftover file would resurrect a retracted link on
    the next daemon restart (which happens on every push to master).
    """
    path = folder / FEEDBACK_FORM_FILE
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


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
    if not isinstance(data, dict):
        return None
    try:
        _URL_VALIDATOR.validate_python(data.get("url"))
    except ValidationError:
        log.error("session", f"Ignoring {FEEDBACK_FORM_FILE}: not a URL: {data.get('url')!r}")
        return None
    return {
        "title": data.get("title", ""),
        "url": data["url"],
        "created_at": data.get("created_at", ""),
    }
