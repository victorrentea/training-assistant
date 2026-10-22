"""Played shorts: the tablet's Video Snippets the room saw in a time window.

Inputs, all optional except the play log (a missing one just means no moments):

- **Play log** — Victor Addons appends one JSON line per snippet it played
  (`{"ts":"2026-10-22T17:32:01.123+03:00","id":"KD_1Z8iUDho","title":"Argentina",
  "startSeconds":145,"kind":"video"}`; `kind` is `soundtrack` for the ♪ button, sound
  only). Path: `$SOUNDBOARD_PLAY_LOG`, else `~/.victor-addons/video-plays.jsonl`.
- **YouTube ledger** — victor-vibe-board's `youtube-publish.json`
  (`$SOUNDBOARD_YOUTUBE_LEDGER`), keyed by the same `id`: the snippet's own upload
  (the played window, with its subtitles), its URL and title. Not published yet →
  `url` is null.

The player auto-kills a snippet 60 s after it starts and a new play replaces the
running one, so `heard_s` is the time to the next play, capped at 60 s. The same
snippet played again within a few seconds is one moment (a restart, not a rerun).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from daemon import log

_NAME = "shorts"

DEFAULT_PLAY_LOG = Path.home() / ".victor-addons" / "video-plays.jsonl"
DEFAULT_LEDGER = Path.home() / "workspace" / "victor-vibe-board" / "youtube-publish.json"
PLAY_SECONDS = 60.0  # Victor Addons' VideoPlayer auto-kill
BURST_GAP_S = 10.0


class Play(BaseModel):
    """One line of the play log, as Victor Addons writes it."""

    ts: datetime
    id: str
    title: str = ""
    startSeconds: int = 0
    kind: str = "video"


class LedgerEntry(BaseModel):
    """The fields of a youtube-publish.json entry this module reads; the rest is ignored."""

    url: str | None = None
    visibility: str | None = None
    title: str | None = None


class ShortMoment(BaseModel):
    """One snippet the room saw (or heard, for a soundtrack play), at the moment it started."""

    ts: str  # first play, ISO-8601 with the local offset
    at: str  # HH:MM local, to line it up with the transcript's [HH:MM]
    id: str
    title: str  # the tablet tile's title, e.g. "Argentina"
    caption: str | None  # the YouTube title — the tile title plus its first subtitle line
    url: str | None
    visibility: str | None
    kind: str  # "video" | "soundtrack"
    heard_s: float | None  # ≈ seconds it ran before the next play cut it (≤ 60); null for the last one
    stopped: bool  # cut short by the next play
    plays: int  # restarts collapsed into this moment


def play_log_path() -> Path:
    return Path(os.environ.get("SOUNDBOARD_PLAY_LOG", str(DEFAULT_PLAY_LOG))).expanduser()


def ledger_path() -> Path:
    return Path(os.environ.get("SOUNDBOARD_YOUTUBE_LEDGER", str(DEFAULT_LEDGER))).expanduser()


def load_plays(path: Path) -> list[Play]:
    if not path.is_file():
        return []
    plays: list[Play] = []
    bad = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            play = Play.model_validate_json(raw)
        except ValidationError:
            bad += 1
            continue
        if play.ts.tzinfo is None:
            play.ts = play.ts.astimezone()
        plays.append(play)
    if bad:
        log.error(_NAME, f"Skipped {bad} malformed line(s) in {path}")
    plays.sort(key=lambda p: p.ts)
    return plays


def load_ledger(path: Path) -> dict[str, LedgerEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ledger: dict[str, LedgerEntry] = {}
    for key, entry in (raw.items() if isinstance(raw, dict) else []):
        try:
            ledger[key] = LedgerEntry.model_validate(entry)
        except ValidationError:
            continue
    return ledger


def collapse(plays: list[Play], ledger: dict[str, LedgerEntry], burst_gap_s: float = BURST_GAP_S) -> list[ShortMoment]:
    """All plays (sorted by ts) → one moment per run of restarts of the same snippet."""
    bursts: list[list[Play]] = []
    for play in plays:
        last = bursts[-1][-1] if bursts else None
        if last and last.id == play.id and (play.ts - last.ts).total_seconds() <= burst_gap_s:
            bursts[-1].append(play)
        else:
            bursts.append([play])

    moments: list[ShortMoment] = []
    for i, burst in enumerate(bursts):
        first, last = burst[0], burst[-1]
        entry = ledger.get(first.id)
        cut_at = bursts[i + 1][0].ts if i + 1 < len(bursts) else None
        if cut_at is None:
            heard, stopped = None, False
        else:
            ran = (cut_at - last.ts).total_seconds()
            heard, stopped = round(min(ran, PLAY_SECONDS), 1), ran < PLAY_SECONDS
        moments.append(
            ShortMoment(
                ts=first.ts.isoformat(timespec="seconds"),
                at=first.ts.strftime("%H:%M"),
                id=first.id,
                title=first.title or (entry.title if entry and entry.title else first.id),
                caption=entry.title if entry else None,
                url=entry.url if entry else None,
                visibility=entry.visibility if entry else None,
                kind=first.kind,
                heard_s=heard,
                stopped=stopped,
                plays=len(burst),
            )
        )
    return moments


def _aware(value: datetime) -> datetime:
    """A naive bound is local time, like the transcript's [HH:MM]."""
    return value if value.tzinfo else value.astimezone()


def moments_between(
    start: datetime,
    end: datetime,
    *,
    play_log: Path | None = None,
    ledger_file: Path | None = None,
    burst_gap_s: float = BURST_GAP_S,
) -> list[ShortMoment]:
    """The moments whose first play falls in [start, end]."""
    start, end = _aware(start), _aware(end)
    # Collapse over the whole log, then window: the play right after `end` still
    # decides how long the last snippet in the window ran.
    moments = collapse(load_plays(play_log or play_log_path()), load_ledger(ledger_file or ledger_path()), burst_gap_s)
    return [m for m in moments if start <= datetime.fromisoformat(m.ts) <= end]
