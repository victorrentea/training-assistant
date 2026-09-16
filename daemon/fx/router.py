"""Daemon FX router — the public half.

Everything here is reachable from the internet through Railway's `/fx/*` relay,
so it is written as a series of refusals: a wrong token is a flat 404 with no
hint which part failed, a closed master switch presses nothing, and a caller
who holds down F5 is answered with a countdown instead of a soundboard.

The press itself takes an **integer** the daemon looked up in the catalog. No
string from a request ever becomes part of a URL on the effects port.
"""
import logging
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from daemon import effects_client
from daemon import log as daemon_log
from daemon.participant.state import participant_state

logger = logging.getLogger(__name__)

_PAGE_PATH = Path(__file__).resolve().parents[2] / "static" / "fx.html"


# ── Pydantic models ──

class FxInfoResponse(BaseModel):
    tile_n: int
    label: str
    effect: str | None
    enabled: bool
    cooldown_seconds: int
    ready_in_seconds: int
    effects_up: bool


class FxFireResponse(BaseModel):
    fired: bool
    # ok | disabled | cooling | effects-down | no-tile
    reason: str
    ready_in_seconds: int


# ── Helpers ──

def tile_label(tile: dict) -> str:
    """A human name for a tile.

    Most manifest rows carry no label, so the filename is the fallback:
    ``69_scream_ghost.mp3`` reads as ``scream ghost``.
    """
    explicit = (tile.get("label") or "").strip()
    if explicit:
        return explicit
    stem = str(tile.get("asset", "")).rsplit(".", 1)[0]
    _, _, rest = stem.partition("_")
    return (rest or stem).replace("_", " ")


def find_tile(n: int) -> dict | None:
    """The catalog row for tile ``n``, or None when the apps are down or the
    number is not in the manifest."""
    for tile in effects_client.fetch_tiles() or []:
        if tile.get("n") == n:
            return tile
    return None


def _check_token(token: str) -> None:
    """404 unless ``token`` is this session's link token.

    `compare_digest` so the answer's timing says nothing about how much of the
    token was right.
    """
    current = participant_state.fx_token
    if not current or not secrets.compare_digest(token, current):
        raise HTTPException(status_code=404)


def cooldown_remaining() -> int:
    """Whole seconds left before the button works again.

    Measured on a monotonic clock: a system clock that jumps must not unlock
    the button early or lock it until tomorrow.
    """
    last = participant_state.fx_last_fired_mono
    if last is None:
        return 0
    elapsed = time.monotonic() - last
    remaining = participant_state.fx_cooldown_seconds - elapsed
    return max(0, int(remaining + 0.999)) if remaining > 0 else 0


# ── Participant router ──

participant_router = APIRouter(prefix="/api/participant/fx", tags=["fx"])


@participant_router.get("/{token}", response_class=HTMLResponse)
async def fx_page(token: str):
    """The trigger page. One button, and an honest account of why it is grey."""
    _check_token(token)
    try:
        return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))
    except OSError:
        logger.error("fx page missing at %s", _PAGE_PATH)
        return HTMLResponse("<h1>FX page unavailable</h1>", status_code=500)


@participant_router.get("/{token}/info", response_model=FxInfoResponse)
async def fx_info(token: str):
    """What the page renders, and what an already-open tab polls for so a host
    toggle reaches it without a reload."""
    _check_token(token)
    n = participant_state.fx_tile_n
    tile = find_tile(n) or {}
    return FxInfoResponse(
        tile_n=n,
        label=tile_label(tile) if tile else f"tile {n}",
        effect=tile.get("effect"),
        enabled=participant_state.fx_enabled,
        cooldown_seconds=participant_state.fx_cooldown_seconds,
        ready_in_seconds=cooldown_remaining(),
        effects_up=effects_client.is_up(),
    )


@participant_router.post("/{token}/fire", response_model=FxFireResponse)
async def fx_fire(token: str):
    """Press the selected tile, if all the brakes are off."""
    _check_token(token)

    # Master switch first: a hand-crafted POST achieves nothing while closed,
    # and nothing below this line runs — no lookup, no log, no press.
    if not participant_state.fx_enabled:
        return FxFireResponse(fired=False, reason="disabled", ready_in_seconds=0)

    remaining = cooldown_remaining()
    if remaining > 0:
        return FxFireResponse(fired=False, reason="cooling", ready_in_seconds=remaining)

    n = participant_state.fx_tile_n
    tile = find_tile(n)
    if tile is None:
        return FxFireResponse(fired=False, reason="no-tile", ready_in_seconds=0)

    if not effects_client.press_tile(n):
        # A press that did not happen must not start a cooldown — otherwise a
        # closed soundboard locks the button for ten seconds per attempt.
        return FxFireResponse(fired=False, reason="effects-down", ready_in_seconds=0)

    participant_state.fx_last_fired_mono = time.monotonic()
    participant_state.fx_last_fired_at = time.time()
    participant_state.persist()

    label = tile_label(tile)
    daemon_log.info("host", f"← 🎛️ fx link fired tile {n} ({label})")

    from daemon.ws_messages import FxFiredMsg
    from daemon.ws_publish import notify_host
    await notify_host(FxFiredMsg(tile_n=n, label=label, at=participant_state.fx_last_fired_at))

    return FxFireResponse(fired=True, reason="ok",
                          ready_in_seconds=participant_state.fx_cooldown_seconds)


@participant_router.get("/{token}/image")
async def fx_image(token: str):
    """Artwork for the selected tile.

    The path handed to the effects app comes from the manifest that app served,
    never from the request — the token in the URL selects nothing but access.
    """
    _check_token(token)
    tile = find_tile(participant_state.fx_tile_n)
    if not tile or not tile.get("image"):
        raise HTTPException(status_code=404)
    fetched = effects_client.fetch_tile_image(str(tile["image"]))
    if fetched is None:
        raise HTTPException(status_code=404)
    body, content_type = fetched
    return Response(content=body, media_type=content_type,
                    headers={"Cache-Control": "no-store"})
