"""The wiki notes the trainer starred as key takeaways of the session.

He stars a note from his own wiki (note-pane.ts → POST 127.0.0.1:1234/wiki/takeaway);
every participant's graph then shows its dot with a filled star and a golden glow.

Kept in the session folder, next to feedback-form.json and outside wiki/: the daemon
restarts on every push to master and the wiki is rebuilt whenever its vault changes,
and the stars must survive both. Read once per session folder and cached, so a
session switch picks up the entered session's stars by itself.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from daemon import log
from daemon.misc.content_files import get_active_session_folder

TAKEAWAYS_FILE = "wiki-takeaways.json"

_lock = threading.Lock()
_cache: tuple[Path, list[str]] | None = None  # (session folder, its starred slugs)


def load_takeaways(folder: Path) -> list[str]:
    """The starred slugs saved in the session folder; [] if none or unreadable."""
    path = folder / TAKEAWAYS_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - a broken file must not break the session state
        log.error("wiki", f"Unreadable {TAKEAWAYS_FILE}: {e}")
        return []
    slugs = data.get("slugs") if isinstance(data, dict) else None
    if not isinstance(slugs, list):
        return []
    return sorted({s for s in slugs if isinstance(s, str) and s})


def _save(folder: Path, slugs: list[str]) -> None:
    path = folder / TAKEAWAYS_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"slugs": slugs}, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _cached(folder: Path) -> list[str]:
    global _cache
    if _cache is None or _cache[0] != folder:
        _cache = (folder, load_takeaways(folder))
    return _cache[1]


def current_takeaways() -> list[str]:
    """The active session's starred slugs, sorted ([] without an active session)."""
    folder = get_active_session_folder()
    if folder is None:
        return []
    with _lock:
        return list(_cached(folder))


def set_takeaway(slug: str, starred: bool) -> list[str] | None:
    """Star or un-star one note; returns the new sorted list, None without an active session."""
    global _cache
    folder = get_active_session_folder()
    if folder is None:
        return None
    with _lock:
        slugs = set(_cached(folder))
        if starred:
            slugs.add(slug)
        else:
            slugs.discard(slug)
        result = sorted(slugs)
        _save(folder, result)
        _cache = (folder, result)
        return list(result)


def forget_cache() -> None:
    """For tests: the next read goes back to disk."""
    global _cache
    with _lock:
        _cache = None
