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
"""
import os

import httpx

from daemon import log

_NAME = "addons   "

EFFECTS_BASE_URL = os.environ.get("VICTOR_ADDONS_URL", "http://127.0.0.1:55123").rstrip("/")

# The apps are on loopback. A slow answer means something is wrong, not far.
_TIMEOUT = 2.0
# Artwork is bigger than JSON and worth a little more patience.
_IMAGE_TIMEOUT = 5.0


def press_tile(n: int) -> bool:
    """Press soundboard tile ``n`` — sound, paired visual, and its own stop.

    Returns False rather than raising when the apps are down. A miss is
    reported by the route in the *body* (``{"ok": false, "reason": ...}``) at
    status 200, so the body is what decides.
    """
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


def fetch_tiles() -> list[dict] | None:
    """The soundboard catalog: every tile's number, asset, artwork and — where
    one is paired — the name of the visual it fires.

    Returns None when the apps are down or no manifest is mounted. Items are
    left as raw dicts on purpose: the manifest is written in the tablet's repo
    and a key added there must survive a daemon that predates it.
    """
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


def is_up() -> bool:
    """Is the effects app reachable and running?

    Reads ``effectsUp`` from the merged ping, so "addons is alive but effects
    is closed" reports False — which is the case that matters here.
    """
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/ping", timeout=_TIMEOUT)
        return r.status_code == 200 and bool(r.json().get("effectsUp"))
    except Exception:
        return False
