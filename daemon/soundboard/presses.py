"""Soundboard presses in a time window, joined into the moments the room heard.

Inputs, all optional except the press log (a missing one just means no moments):

- **Press log** — victor-effects appends one JSON line per counted press
  (`{"ts":"2026-10-22T17:32:01.123+03:00","file":"53b_7_rings.mp3","n":53,
  "layer":"b","source":"tablet"}`). Path: `$SOUNDBOARD_PRESS_LOG`, else the
  `pressLogFile` key of `~/.victor-effects/config.json`, else
  `~/.victor-effects/presses.jsonl`.
- **Grid** — the tablet's `tiles.json` (`$SOUNDBOARD_TILES_FILE`): fills `n`/`layer`
  when the log has none, gives the `label` and whether a tile is `restartable`.
- **Captions** — victor-effects' `GET /sounds/captions` (through the addons door,
  `$VICTOR_ADDONS_URL`) or a JSON file with the same shape (`$SOUNDBOARD_CAPTIONS`):
  the clip's length and the words the room saw on screen.
- **YouTube ledger** — victor-vibe-board's `youtube-publish.json`
  (`$SOUNDBOARD_YOUTUBE_LEDGER`): the clip's public/unlisted URL. Not published yet
  → `url` is null.

A tile tapped twice within a few seconds is one moment, not two: on the tablet a
re-tap stops a playing clip (or restarts it, on a `restartable` tile), so a stop and
restart is still the one clip the room heard. `heard_s` and `stopped` estimate what
was actually heard, so a reader can drop the accidental taps.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from daemon import log

_NAME = "sndbrd"

DEFAULT_PRESS_LOG = Path.home() / ".victor-effects" / "presses.jsonl"
EFFECTS_CONFIG = Path.home() / ".victor-effects" / "config.json"
DEFAULT_TILES_FILE = (
    Path.home() / "workspace" / "victor-vibe-board" / "app" / "src" / "main" / "assets" / "tiles.json"
)
DEFAULT_LEDGER = Path.home() / "workspace" / "victor-vibe-board" / "youtube-publish.json"
DEFAULT_CAPTIONS = os.environ.get("VICTOR_ADDONS_URL", "http://127.0.0.1:55123").rstrip("/") + "/sounds/captions"

# Same tile pressed again within this many seconds of its previous press, with no
# other tile in between → the same moment (a stop and restart, or a nervous double tap).
BURST_GAP_S = 5.0
_CAPTIONS_TIMEOUT_S = 2.0


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class Press(BaseModel):
    """One line of the press log, as victor-effects writes it."""

    ts: datetime
    file: str
    n: int | None = None
    layer: Literal["a", "b"] | None = None
    source: str | None = None


class Tile(BaseModel):
    """What the grid knows about one asset."""

    n: int
    layer: Literal["a", "b"]
    label: str | None = None
    restartable: bool = False


class CaptionCue(BaseModel):
    start: float
    end: float
    text: str


class ClipCaptions(BaseModel):
    durationSeconds: float | None = None
    cues: list[CaptionCue] = []


class LedgerEntry(BaseModel):
    """The fields of a youtube-publish.json entry this module reads; the rest is ignored."""

    url: str | None = None
    visibility: str | None = None
    title: str | None = None


class SoundboardMoment(BaseModel):
    """One clip the room heard, at the moment it was fired."""

    ts: str  # first press, ISO-8601 with the local offset
    at: str  # HH:MM local, to line it up with the transcript's [HH:MM]
    n: int | None
    layer: Literal["a", "b"] | None
    file: str
    title: str
    caption: str | None
    url: str | None
    visibility: str | None
    duration_s: float | None  # the clip's full length, when the captions say
    heard_s: float | None  # ≈ how long it actually played; null when unknown
    stopped: bool  # the last tap of the burst stopped it
    presses: int  # taps collapsed into this moment
    source: str | None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def press_log_path() -> Path:
    env = os.environ.get("SOUNDBOARD_PRESS_LOG")
    if env:
        return Path(env).expanduser()
    try:
        configured = json.loads(EFFECTS_CONFIG.read_text(encoding="utf-8")).get("pressLogFile")
    except (OSError, ValueError, AttributeError):
        configured = None
    return Path(configured).expanduser() if configured else DEFAULT_PRESS_LOG


def tiles_path() -> Path:
    return Path(os.environ.get("SOUNDBOARD_TILES_FILE", str(DEFAULT_TILES_FILE))).expanduser()


def ledger_path() -> Path:
    return Path(os.environ.get("SOUNDBOARD_YOUTUBE_LEDGER", str(DEFAULT_LEDGER))).expanduser()


def captions_source() -> str:
    return os.environ.get("SOUNDBOARD_CAPTIONS", DEFAULT_CAPTIONS)


# ---------------------------------------------------------------------------
# Loaders — each one best-effort: a missing or broken input degrades, never raises
# ---------------------------------------------------------------------------


def load_presses(path: Path) -> list[Press]:
    if not path.is_file():
        return []
    presses: list[Press] = []
    bad = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            press = Press.model_validate_json(raw)
        except ValidationError:
            bad += 1
            continue
        if press.ts.tzinfo is None:
            press.ts = press.ts.astimezone()
        presses.append(press)
    if bad:
        log.error(_NAME, f"Skipped {bad} malformed line(s) in {path}")
    presses.sort(key=lambda p: p.ts)
    return presses


def load_tiles(path: Path) -> dict[str, Tile]:
    """asset file → Tile, for both layers (`under` is layer B)."""
    try:
        grid = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tiles: dict[str, Tile] = {}
    for entry in grid.get("tiles") or []:
        n = entry.get("n")
        if not isinstance(n, int):
            continue
        if entry.get("asset"):
            tiles[entry["asset"]] = Tile(
                n=n, layer="a", label=entry.get("label"), restartable=bool(entry.get("restartable"))
            )
        under = entry.get("under") or {}
        if under.get("asset"):
            tiles[under["asset"]] = Tile(
                n=n, layer="b", label=under.get("label"), restartable=bool(under.get("restartable"))
            )
    return tiles


def load_ledger(path: Path) -> dict[str, LedgerEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ledger: dict[str, LedgerEntry] = {}
    for file, entry in (raw.items() if isinstance(raw, dict) else []):
        try:
            ledger[file] = LedgerEntry.model_validate(entry)
        except ValidationError:
            continue
    return ledger


def load_captions(source: str) -> dict[str, ClipCaptions]:
    """From victor-effects' `/sounds/captions` URL, or a JSON file of the same shape."""
    if not source:
        return {}
    try:
        if source.startswith(("http://", "https://")):
            r = httpx.get(source, timeout=_CAPTIONS_TIMEOUT_S)
            if r.status_code != 200:
                return {}
            raw = r.json()
        else:
            raw = json.loads(Path(source).expanduser().read_text(encoding="utf-8"))
    except (httpx.HTTPError, OSError, ValueError):
        return {}
    captions: dict[str, ClipCaptions] = {}
    for file, entry in (raw.items() if isinstance(raw, dict) else []):
        try:
            captions[file] = ClipCaptions.model_validate(entry)
        except ValidationError:
            continue
    return captions


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------

_NUMBER_PREFIX = re.compile(r"^\d+[a-z]?_")


def clip_title(file: str, tile: Tile | None) -> str:
    """`53b_7_rings.mp3` → `7 Rings`; a tile's own label (`HELLO`) wins."""
    if tile and tile.label:
        return tile.label.strip().title()
    words = _NUMBER_PREFIX.sub("", Path(file).stem).replace("_", " ").split()
    return " ".join(w[:1].upper() + w[1:] for w in words) or file


def _heard(
    burst: list[Press], restartable: bool, duration: float | None, cut_at: datetime | None
) -> tuple[float | None, bool]:
    """(≈ seconds heard, stopped by the last tap) for one burst of taps on one tile.

    Replays the tablet's rule: a tap on a playing, non-restartable clip stops it; any
    other tap (re)starts it. A tap on a different tile (`cut_at`) also ends it — only
    one sound plays at a time.
    """
    heard = 0.0
    playing_from: datetime | None = None
    for press in burst:
        if playing_from is not None:
            elapsed = (press.ts - playing_from).total_seconds()
            still_playing = duration is None or elapsed < duration
            heard += min(elapsed, duration) if duration is not None else elapsed
            playing_from = None
            if still_playing and not restartable:
                continue  # this tap was a stop
        playing_from = press.ts
    if playing_from is None:
        return round(heard, 1), True
    if duration is None:  # it played on until… nobody knows; a later tap is only a bound
        return None, False
    tail = duration if cut_at is None else min((cut_at - playing_from).total_seconds(), duration)
    return round(heard + tail, 1), False


def collapse(
    presses: list[Press],
    tiles: dict[str, Tile],
    captions: dict[str, ClipCaptions],
    ledger: dict[str, LedgerEntry],
    burst_gap_s: float = BURST_GAP_S,
) -> list[SoundboardMoment]:
    """All presses (sorted by ts) → one moment per burst of taps on the same tile."""
    bursts: list[list[Press]] = []
    for press in presses:
        last = bursts[-1][-1] if bursts else None
        if last and last.file == press.file and (press.ts - last.ts).total_seconds() <= burst_gap_s:
            bursts[-1].append(press)
        else:
            bursts.append([press])

    moments: list[SoundboardMoment] = []
    for i, burst in enumerate(bursts):
        first = burst[0]
        tile = tiles.get(first.file)
        clip = captions.get(first.file)
        entry = ledger.get(first.file)
        duration = clip.durationSeconds if clip else None
        cut_at = bursts[i + 1][0].ts if i + 1 < len(bursts) else None
        heard, stopped = _heard(burst, bool(tile and tile.restartable), duration, cut_at)
        caption = " / ".join(c.text.strip() for c in clip.cues if c.text.strip()) if clip else ""
        local = first.ts  # keep the offset the Mac logged: that is the transcript's clock
        moments.append(
            SoundboardMoment(
                ts=local.isoformat(timespec="seconds"),
                at=local.strftime("%H:%M"),
                n=first.n if first.n is not None else (tile.n if tile else None),
                layer=first.layer or (tile.layer if tile else None),
                file=first.file,
                title=clip_title(first.file, tile),
                caption=caption or None,
                url=entry.url if entry else None,
                visibility=entry.visibility if entry else None,
                duration_s=duration,
                heard_s=heard,
                stopped=stopped,
                presses=len(burst),
                source=first.source,
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
    press_log: Path | None = None,
    tiles_file: Path | None = None,
    captions: str | None = None,
    ledger_file: Path | None = None,
    burst_gap_s: float = BURST_GAP_S,
) -> list[SoundboardMoment]:
    """The moments whose first tap falls in [start, end]."""
    start, end = _aware(start), _aware(end)
    presses = load_presses(press_log or press_log_path())
    # Collapse over the whole log, then window: the press right after `end` still
    # decides how long the last clip in the window played.
    moments = collapse(
        presses,
        load_tiles(tiles_file or tiles_path()),
        load_captions(captions if captions is not None else captions_source()),
        load_ledger(ledger_file or ledger_path()),
        burst_gap_s,
    )
    return [m for m in moments if start <= datetime.fromisoformat(m.ts) <= end]
