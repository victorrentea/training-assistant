"""HTTP client for the Mac's soundboard apps.

One door: Victor Addons on :55123, which forwards everything about tiles,
sounds and effects to Victor Effects on :55124 and merges the two halves of
`/ping`. The daemon never needs to know the second port exists.

Best-effort throughout, like `addon_bridge_client`: the apps are allowed to be
closed, and nothing here may raise into a request handler.

SECURITY: `press_tile` takes an **int**. Nothing a caller types ever reaches
these URLs as a path segment — the effects ports have no authentication and
bind every interface, so keeping caller strings out of them is what stops an
internet-facing link from becoming a way to drive the trainer's Mac.

ASYNC: every public function here is a coroutine that runs its `httpx.get`
on a worker thread via `asyncio.to_thread` — the same pattern every other
router in this daemon uses for blocking I/O (see `misc/router.py`,
`slides/router.py`, `participant/router.py`). It is done *inside* the client,
not at each call site: `/api/participant/fx/*` is the one route reachable
from the public internet, called from many places in `fx/router.py`, and a
caller who forgets to wrap one of those call sites would silently put a
`_TIMEOUT`-sized (or, for `press_tile`, up to `2 * _TIMEOUT`) stall back on
the event loop — exactly the bug this module exists to not have again. Making
the client itself non-blocking means every caller is safe by construction.

CACHING: `fetch_tiles()` and `is_up()` are cached for `_READ_CACHE_TTL`
seconds. The soundboard catalog changes on the timescale of a file edit on
the Mac, not of a browser poll every few seconds, and `is_up()` is a coarse
liveness check — so a couple of seconds of staleness costs nothing a human
would notice, while it collapses a room full of participant tabs (each
polling `/info`, which calls both) into one outbound request per TTL window
instead of two per participant per poll. `press_tile()` is never cached: it
is the one call here with a real-world side effect, not a read.
"""
import asyncio
import os
import time

import httpx

from daemon import log

_NAME = "addons   "

EFFECTS_BASE_URL = os.environ.get("VICTOR_ADDONS_URL", "http://127.0.0.1:55123").rstrip("/")

# The apps are on loopback. A slow answer means something is wrong, not far.
_TIMEOUT = 2.0
# Artwork is bigger than JSON and worth a little more patience.
_IMAGE_TIMEOUT = 5.0

# Every participant page re-reads `/info` when the daemon broadcasts
# `fx_changed` (see static/participant.html), so a single host click — a
# grant-all above all — turns into one `/info` per tab at the same instant.
# A cache of a couple of seconds collapses that whole burst into one outbound
# request per TTL window, which is the case this cache exists for.
_READ_CACHE_TTL = 2.0

_tiles_cache_at: float | None = None
_tiles_cache_value: list[dict] | None = None

_up_cache_at: float | None = None
_up_cache_value: bool = False


def _press_tile_sync(n: int) -> bool:
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/press/{int(n)}", timeout=_TIMEOUT)
        if r.status_code != 200:
            log.info(_NAME, f"✗ press {n} (HTTP {r.status_code})")
            return False
        body = r.json()
    except Exception as e:
        log.info(_NAME, f"✗ press {n} ({type(e).__name__})")
        return False
    if not body.get("ok"):
        log.info(_NAME, f"✗ press {n} ({body.get('reason', 'refused')})")
        return False
    log.info(_NAME, f"→ press {n} ({body.get('asset', '?')})")
    return True


async def press_tile(n: int) -> bool:
    """Press soundboard tile ``n`` — sound, paired visual, and its own stop.

    Returns False rather than raising when the apps are down. A miss is
    reported by the route in the *body* (``{"ok": false, "reason": ...}``) at
    status 200, so the body is what decides.

    Never cached — a press is an action, not a read, and the host's Test
    button and a genuine participant fire both need the real, current answer.
    """
    return await asyncio.to_thread(_press_tile_sync, n)


def _fetch_tiles_sync() -> list[dict] | None:
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/tiles", timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        tiles = r.json().get("tiles")
    except Exception:
        return None
    if not isinstance(tiles, list) or not tiles:
        return None
    return tiles


async def fetch_tiles() -> list[dict] | None:
    """The soundboard catalog: every tile's number, asset, artwork and — where
    one is paired — the name of the visual it fires.

    Returns None when the apps are down or no manifest is mounted. Items are
    left as raw dicts on purpose: the manifest is written in the tablet's repo
    and a key added there must survive a daemon that predates it.

    Cached for `_READ_CACHE_TTL` — see the module docstring.
    """
    global _tiles_cache_at, _tiles_cache_value
    now = time.monotonic()
    if _tiles_cache_at is not None and now - _tiles_cache_at < _READ_CACHE_TTL:
        return _tiles_cache_value
    value = await asyncio.to_thread(_fetch_tiles_sync)
    _tiles_cache_at = now
    _tiles_cache_value = value
    return value


def _is_up_sync() -> bool:
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/ping", timeout=_TIMEOUT)
        return r.status_code == 200 and bool(r.json().get("effectsUp"))
    except Exception:
        return False


async def is_up() -> bool:
    """Is the effects app reachable and running?

    Reads ``effectsUp`` from the merged ping, so "addons is alive but effects
    is closed" reports False — which is the case that matters here.

    Cached for `_READ_CACHE_TTL` — see the module docstring. A real press
    outcome (`participant_state.fx_last_press_ok`, tracked in `fx/router.py`)
    is never cached and always overrides a stale "up" here, so this cache
    cannot make the button look ready right after a genuine press just failed.
    """
    global _up_cache_at, _up_cache_value
    now = time.monotonic()
    if _up_cache_at is not None and now - _up_cache_at < _READ_CACHE_TTL:
        return _up_cache_value
    value = await asyncio.to_thread(_is_up_sync)
    _up_cache_at = now
    _up_cache_value = value
    return value
