"""The wiki notes participants star as interesting, so they shine for the whole group.

A participant clicks the star by a dot in the participant page's Wiki tab (note-pane.ts
→ the page → POST /api/participant/wiki/star), or in the wiki opened in a tab of its own
(note-pane.ts → POST, with the UUID the participant page left in localStorage); every
graph then shows how many starred
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

Private until the trainer reveals them (Victor, 2026-11-12): while he scans the wiki
with the room, each participant sees only their own stars, so nobody just copies the
crowd, and clicks Done when finished; the trainer's graph shows every star and how many
are done (🏁). His toggle then shows everyone's stars to everyone; hiding them again
starts a new round, so the Done count starts over. The participants never get the
others' counts while hidden: the daemon leaves them out of every answer and broadcast.

Kept in the session folder next to wiki-takeaways.json, for the same reason: the daemon
restarts on every push to master and the wiki is rebuilt whenever its vault changes, and
the stars must survive both. Read once per session folder and cached.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from daemon import log
from daemon.misc.content_files import get_active_session_folder

STARS_FILE = "wiki-stars.json"

# Toggles one participant may make in a sliding window: plenty for real clicking,
# useless for flooding.
RATE_LIMIT = 30
RATE_WINDOW_S = 60.0



@dataclass
class _Board:
    stars: dict[str, set[str]] = field(default_factory=dict)  # slug -> starring pids
    revealed: bool = False  # everyone sees everyone's stars; else each sees only their own
    done: set[str] = field(default_factory=set)  # pids who clicked Done this round


_lock = threading.Lock()
_cache: tuple[Path, _Board] | None = None  # (session folder, its board)
_recent: dict[str, deque[float]] = {}
_version = 0  # bumped on every saved change: the vault's star lines follow it (star_lines.py)


def _load_board(folder: Path) -> _Board:
    """The board saved in the session folder; an empty one if none or unreadable."""
    path = folder / STARS_FILE
    if not path.exists():
        return _Board()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - a broken file must not break the session state
        log.error("wiki", f"Unreadable {STARS_FILE}: {e}")
        return _Board()
    if not isinstance(data, dict):
        return _Board()
    board = _Board(revealed=data.get("revealed") is True)
    done = data.get("done")
    if isinstance(done, list):
        board.done = {p for p in done if isinstance(p, str) and p}
    stars = data.get("stars")
    if not isinstance(stars, dict):
        return board
    for slug, pids in stars.items():
        if isinstance(slug, str) and slug and isinstance(pids, list):
            valid = {p for p in pids if isinstance(p, str) and p}
            if valid:
                board.stars[slug] = valid
    return board


def load_stars(folder: Path) -> dict[str, set[str]]:
    """The stars saved in the session folder; {} if none or unreadable."""
    return _load_board(folder).stars


def _save(folder: Path, board: _Board, stars_changed: bool = True) -> None:
    global _version
    if stars_changed:
        _version += 1
    path = folder / STARS_FILE
    tmp = path.with_name(path.name + ".tmp")
    payload = {
        "stars": {slug: sorted(pids) for slug, pids in sorted(board.stars.items()) if pids},
        "revealed": board.revealed,
        "done": sorted(board.done),
    }
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _cached(folder: Path) -> _Board:
    global _cache
    if _cache is None or _cache[0] != folder:
        _cache = (folder, _load_board(folder))
    return _cache[1]


def _counts(stars: dict[str, set[str]]) -> dict[str, int]:
    return {slug: len(pids) for slug, pids in sorted(stars.items()) if pids}


def star_counts() -> dict[str, int]:
    """How many participants starred each note of the active session ({} without one)."""
    folder = get_active_session_folder()
    if folder is None:
        return {}
    with _lock:
        return _counts(_cached(folder).stars)


def counts_in(folder: Path) -> tuple[int, dict[str, int]]:
    """(version, counts) of a session folder's stars: the version tells a reader that
    mirrors them whether anything changed since it last looked."""
    with _lock:
        return _version, _counts(_cached(folder).stars)


def starrer_count() -> int:
    """How many participants starred at least one note: the graph shows it to draw in
    the rest of the room (Victor, 2026-11-09)."""
    folder = get_active_session_folder()
    if folder is None:
        return 0
    with _lock:
        return len(set().union(*_cached(folder).stars.values()))


def stars_of(pid: str) -> list[str]:
    """The notes this participant starred, sorted."""
    folder = get_active_session_folder()
    if folder is None:
        return []
    with _lock:
        return sorted(slug for slug, pids in _cached(folder).stars.items() if pid in pids)


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
        board = _cached(folder)
        stars = board.stars
        pids = stars.setdefault(slug, set())
        changed = (pid not in pids) if starred else (pid in pids)
        if starred:
            pids.add(pid)
        else:
            pids.discard(pid)
        if not pids:
            del stars[slug]
        if changed:
            _save(folder, board)
        return _counts(stars)


def forget_participant(pid: str) -> int:
    """Withdraw every star of a deleted participant; how many there were."""
    folder = get_active_session_folder()
    _recent.pop(pid, None)
    if folder is None:
        return 0
    with _lock:
        board = _cached(folder)
        stars = board.stars
        hit = [slug for slug, pids in stars.items() if pid in pids]
        for slug in hit:
            stars[slug].discard(pid)
            if not stars[slug]:
                del stars[slug]
        was_done = pid in board.done
        board.done.discard(pid)
        if hit or was_done:
            _save(folder, board, stars_changed=bool(hit))
        return len(hit)


def visible_counts(pid: str | None) -> dict[str, int]:
    """The counts a participant may see: everyone's once revealed, else only their own
    stars, each as 1 (pid None: a reader who starred nothing, so none)."""
    folder = get_active_session_folder()
    if folder is None:
        return {}
    with _lock:
        board = _cached(folder)
        if board.revealed:
            return _counts(board.stars)
        return {slug: 1 for slug, pids in sorted(board.stars.items()) if pid and pid in pids}


def revealed() -> bool:
    """Whether everyone sees everyone's stars (False without a session: nothing to see)."""
    folder = get_active_session_folder()
    if folder is None:
        return False
    with _lock:
        return _cached(folder).revealed


def set_revealed(on: bool) -> bool | None:
    """The trainer shows everyone's stars to everyone, or hides them again: hiding them
    starts a new round, so nobody is Done in it yet. The new state, None without a session."""
    folder = get_active_session_folder()
    if folder is None:
        return None
    with _lock:
        board = _cached(folder)
        if board.revealed == on:
            return on
        board.revealed = on
        if not on:
            board.done.clear()
        _save(folder, board, stars_changed=False)
        return on


def is_done(pid: str | None) -> bool:
    folder = get_active_session_folder()
    if folder is None or not pid:
        return False
    with _lock:
        return pid in _cached(folder).done


def set_done(pid: str, done: bool) -> bool | None:
    """A participant is done looking through the wiki (or takes it back); None without a session."""
    folder = get_active_session_folder()
    if folder is None:
        return None
    with _lock:
        board = _cached(folder)
        if (pid in board.done) != done:
            if done:
                board.done.add(pid)
            else:
                board.done.discard(pid)
            _save(folder, board, stars_changed=False)
        return done


def done_count() -> int:
    """How many participants clicked Done this round (the trainer's 🏁)."""
    folder = get_active_session_folder()
    if folder is None:
        return 0
    with _lock:
        return len(_cached(folder).done)


def forget_cache() -> None:
    """For tests: the next read goes back to disk, and no rate limit carries over."""
    global _cache
    with _lock:
        _cache = None
        _recent.clear()
