"""The wiki notes participants star as interesting, so they shine for the whole group.

A participant clicks the star by a dot in the participant page's Wiki tab (note-pane.ts
→ the page → POST /api/participant/wiki/star); every graph then shows how many starred
it, and the dot shines with the same gold starburst as the trainer's key takeaways,
stronger the more people starred it (Victor, 2026-10-21).

Why a star can't be forged or stuffed:
  - who: the X-Participant-ID header, a crypto.randomUUID() (122 random bits from the
    browser's CSPRNG) that only that participant's browser holds. The daemon never
    hands UUIDs out: the broadcast and every other participant's state carry counts
    only. Guessing someone else's UUID is out of reach, so nobody stars on their behalf.
  - only registered participants: an unknown UUID is refused, so a script minting
    fresh UUIDs gets nothing until each one joins - and every join is a new name on the
    trainer's roster, which he can delete (purge.py drops its stars too).
  - one star per participant per note: a set, so repeating the click changes nothing.
  - only notes of the published wiki: no arbitrary keys growing the file.
  - a per-participant rate limit, and the broadcast is throttled.

Kept in the session folder next to wiki-takeaways.json, for the same reason: the daemon
restarts on every push to master and the wiki is rebuilt whenever its vault changes, and
the stars must survive both. Read once per session folder and cached.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path

from daemon import log
from daemon.misc.content_files import get_active_session_folder

STARS_FILE = "wiki-stars.json"

# Toggles one participant may make in a sliding window: plenty for real clicking,
# useless for flooding.
RATE_LIMIT = 30
RATE_WINDOW_S = 60.0

_lock = threading.Lock()
_cache: tuple[Path, dict[str, set[str]]] | None = None  # (session folder, slug -> starring pids)
_recent: dict[str, deque[float]] = {}


def load_stars(folder: Path) -> dict[str, set[str]]:
    """The stars saved in the session folder; {} if none or unreadable."""
    path = folder / STARS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - a broken file must not break the session state
        log.error("wiki", f"Unreadable {STARS_FILE}: {e}")
        return {}
    stars = data.get("stars") if isinstance(data, dict) else None
    if not isinstance(stars, dict):
        return {}
    result: dict[str, set[str]] = {}
    for slug, pids in stars.items():
        if isinstance(slug, str) and slug and isinstance(pids, list):
            valid = {p for p in pids if isinstance(p, str) and p}
            if valid:
                result[slug] = valid
    return result


def _save(folder: Path, stars: dict[str, set[str]]) -> None:
    path = folder / STARS_FILE
    tmp = path.with_name(path.name + ".tmp")
    payload = {"stars": {slug: sorted(pids) for slug, pids in sorted(stars.items()) if pids}}
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _cached(folder: Path) -> dict[str, set[str]]:
    global _cache
    if _cache is None or _cache[0] != folder:
        _cache = (folder, load_stars(folder))
    return _cache[1]


def _counts(stars: dict[str, set[str]]) -> dict[str, int]:
    return {slug: len(pids) for slug, pids in sorted(stars.items()) if pids}


def star_counts() -> dict[str, int]:
    """How many participants starred each note of the active session ({} without one)."""
    folder = get_active_session_folder()
    if folder is None:
        return {}
    with _lock:
        return _counts(_cached(folder))


def stars_of(pid: str) -> list[str]:
    """The notes this participant starred, sorted."""
    folder = get_active_session_folder()
    if folder is None:
        return []
    with _lock:
        return sorted(slug for slug, pids in _cached(folder).items() if pid in pids)


def allow(pid: str, now: float | None = None) -> bool:
    """Count one toggle against the participant's rate limit; False once over it."""
    now = time.monotonic() if now is None else now
    with _lock:
        recent = _recent.setdefault(pid, deque())
        while recent and now - recent[0] > RATE_WINDOW_S:
            recent.popleft()
        if len(recent) >= RATE_LIMIT:
            return False
        recent.append(now)
        return True


def set_star(pid: str, slug: str, starred: bool) -> dict[str, int] | None:
    """Star or un-star one note for one participant; the new counts, None without a session."""
    folder = get_active_session_folder()
    if folder is None:
        return None
    with _lock:
        stars = _cached(folder)
        pids = stars.setdefault(slug, set())
        changed = (pid not in pids) if starred else (pid in pids)
        if starred:
            pids.add(pid)
        else:
            pids.discard(pid)
        if not pids:
            del stars[slug]
        if changed:
            _save(folder, stars)
        return _counts(stars)


def forget_participant(pid: str) -> int:
    """Withdraw every star of a deleted participant; how many there were."""
    folder = get_active_session_folder()
    _recent.pop(pid, None)
    if folder is None:
        return 0
    with _lock:
        stars = _cached(folder)
        hit = [slug for slug, pids in stars.items() if pid in pids]
        for slug in hit:
            stars[slug].discard(pid)
            if not stars[slug]:
                del stars[slug]
        if hit:
            _save(folder, stars)
        return len(hit)


def forget_cache() -> None:
    """For tests: the next read goes back to disk, and no rate limit carries over."""
    global _cache
    with _lock:
        _cache = None
        _recent.clear()
