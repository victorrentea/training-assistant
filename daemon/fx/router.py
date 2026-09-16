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

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from daemon import effects_client
from daemon import log as daemon_log
from daemon.fx.token import generate_fx_token
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
    tile_available: bool


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


async def find_tile(n: int) -> dict | None:
    """The catalog row for tile ``n``, or None when the apps are down or the
    number is not in the manifest."""
    for tile in await effects_client.fetch_tiles() or []:
        if tile.get("n") == n:
            return tile
    return None


def _check_token(token: str) -> None:
    """404 unless ``token`` is this session's link token.

    Compares UTF-8 *bytes*, not the two `str` objects directly: `compare_digest`
    raises TypeError on a non-ASCII `str` operand, and this endpoint is reached
    by more than the token-alphabet-anchored Railway relay — a second, pre-existing
    route (`/{session_id}/api/participant/fx/...`) forwards whatever the URL
    contains, unfiltered. A raise here becomes a 500, and a 500 is worse than an
    unhelpful 404: it tells a prober their input broke something, and it is the
    one answer this whole feature is built never to give — every other input,
    right or wrong, gets the same flat refusal.

    `errors="surrogatepass"` on the encode keeps this from raising too — plain
    `str.encode("utf-8")` itself raises on a lone surrogate, which a malformed
    percent-encoded path can produce. Comparing bytes still runs `compare_digest`
    in constant time for equal-length input, exactly as the `str` form did.
    """
    current = participant_state.fx_token
    if not current:
        raise HTTPException(status_code=404)
    token_bytes = token.encode("utf-8", errors="surrogatepass")
    current_bytes = current.encode("utf-8")
    if not secrets.compare_digest(token_bytes, current_bytes):
        raise HTTPException(status_code=404)


async def _effects_reachable() -> bool:
    """Whether the next press is expected to work — not just whether the apps
    answer a ping.

    A ping and a press are different calls: `/ping` can succeed while the apps
    lack the `/press/<n>` route a press actually needs (exactly the case while
    the running Mac apps predate that route), and `is_up()` alone can't see
    that. Once a real press has been attempted this session (a participant
    fire or the host's Test button), its outcome overrides the ping — until a
    later attempt succeeds again — so /info never tells the page a press would
    work when the last one just proved otherwise.
    """
    if not await effects_client.is_up():
        return False
    return participant_state.fx_last_press_ok is not False


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
    tile = await find_tile(n) or {}
    return FxInfoResponse(
        tile_n=n,
        label=tile_label(tile) if tile else f"tile {n}",
        effect=tile.get("effect"),
        enabled=participant_state.fx_enabled,
        cooldown_seconds=participant_state.fx_cooldown_seconds,
        ready_in_seconds=cooldown_remaining(),
        effects_up=await _effects_reachable(),
        tile_available=bool(tile),
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
    tile = await find_tile(n)
    if tile is None:
        return FxFireResponse(fired=False, reason="no-tile", ready_in_seconds=0)

    if not await effects_client.press_tile(n):
        # A press that did not happen must not start a cooldown — otherwise a
        # closed soundboard locks the button for ten seconds per attempt.
        # It does, however, update what /info believes: see _effects_reachable().
        participant_state.fx_last_press_ok = False
        return FxFireResponse(fired=False, reason="effects-down", ready_in_seconds=0)

    participant_state.fx_last_press_ok = True
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


# ── Host router (called directly on daemon loopback, like the attention host router) ──

class FxTile(BaseModel):
    n: int
    label: str
    effect: str | None
    image: str
    has_effect: bool


class FxCatalogResponse(BaseModel):
    tiles: list[FxTile]


class FxStateResponse(BaseModel):
    enabled: bool
    token: str
    url: str
    tile_n: int
    tile_label: str
    effect: str | None
    cooldown_seconds: int
    last_fired_at: float | None
    effects_up: bool


class FxTileRequest(BaseModel):
    n: int


class FxCooldownRequest(BaseModel):
    # Five minutes is already absurd for a party trick; the cap keeps a typo
    # from parking the button for the rest of the workshop.
    seconds: int = Field(ge=0, le=300)


host_router = APIRouter(prefix="/api/{session_id}/host/fx", tags=["fx"])


def _public_base_url() -> str:
    """Where participants reach this workshop. Same source as the join link."""
    return os.environ.get("WORKSHOP_SERVER_URL", "http://localhost:8000").rstrip("/")


def _ensure_token() -> str:
    """This session's link token, minted on first use.

    Lazy so a session that never opens the popover never carries a credential.
    """
    if not participant_state.fx_token:
        participant_state.fx_token = generate_fx_token()
        participant_state.persist()
    return participant_state.fx_token


async def _state_response() -> FxStateResponse:
    token = _ensure_token()
    n = participant_state.fx_tile_n
    tile = await find_tile(n) or {}
    return FxStateResponse(
        enabled=participant_state.fx_enabled,
        token=token,
        url=f"{_public_base_url()}/fx/{token}",
        tile_n=n,
        tile_label=tile_label(tile) if tile else f"tile {n}",
        effect=tile.get("effect"),
        cooldown_seconds=participant_state.fx_cooldown_seconds,
        last_fired_at=participant_state.fx_last_fired_at,
        effects_up=await _effects_reachable(),
    )


@host_router.get("/state", response_model=FxStateResponse)
async def fx_state():
    """Everything the footer badge and its popover render."""
    return await _state_response()


@host_router.get("/catalog", response_model=FxCatalogResponse)
async def fx_catalog():
    """The 91 tiles, read live from the Mac.

    Built at request time rather than kept in a list here: adding a tile is a
    JSON entry plus an image in another repo, and a hand-maintained copy would
    be wrong by the next workshop. A closed soundboard is an empty catalog, not
    an error — the popover says so itself.
    """
    tiles = await effects_client.fetch_tiles() or []
    return FxCatalogResponse(tiles=[
        FxTile(
            n=int(t.get("n", 0)),
            label=tile_label(t),
            effect=t.get("effect"),
            image=str(t.get("image", "")),
            has_effect=bool(t.get("effect")),
        )
        for t in tiles if isinstance(t.get("n"), int)
    ])


@host_router.post("/toggle", response_model=FxStateResponse)
async def fx_toggle():
    """Arm or disarm the link. Off at the start of every session."""
    participant_state.fx_enabled = not participant_state.fx_enabled
    participant_state.persist()
    daemon_log.info("host", f"🎛️ fx link {'armed' if participant_state.fx_enabled else 'disarmed'}")
    return await _state_response()


@host_router.post("/tile", response_model=FxStateResponse)
async def fx_set_tile(body: FxTileRequest):
    """Bind the link to a different tile."""
    if await find_tile(body.n) is None:
        raise HTTPException(status_code=404, detail="Unknown tile")
    participant_state.fx_tile_n = body.n
    participant_state.persist()
    daemon_log.info("host", f"🎛️ fx link now fires tile {body.n}")
    return await _state_response()


@host_router.post("/cooldown", response_model=FxStateResponse)
async def fx_set_cooldown(body: FxCooldownRequest):
    """Change how often the room may pull the lever."""
    participant_state.fx_cooldown_seconds = body.seconds
    participant_state.persist()
    return await _state_response()


@host_router.post("/rotate", response_model=FxStateResponse)
async def fx_rotate():
    """Mint a new token, killing the current link immediately."""
    participant_state.fx_token = generate_fx_token()
    participant_state.fx_last_fired_mono = None
    participant_state.persist()
    daemon_log.info("host", "🎛️ fx link rotated — the old URL is dead")
    return await _state_response()


@host_router.post("/test", response_model=FxFireResponse)
async def fx_test():
    """Fire the selected tile from the host page.

    Deliberately ignores both brakes: you check the wiring precisely when the
    link is disarmed, and a cooldown meant for the room should not make the
    trainer wait. It does not start a cooldown either — testing must not take
    the lever away from someone holding the link.

    This is also the room's only recovery path once a real press has failed:
    /info trusts the last actual attempt over the ping (see
    _effects_reachable()), so after a failure the participant button stays
    disabled until a Test from here proves the wiring works again.
    """
    tile = await find_tile(participant_state.fx_tile_n)
    if tile is None:
        return FxFireResponse(fired=False, reason="no-tile", ready_in_seconds=0)
    if not await effects_client.press_tile(participant_state.fx_tile_n):
        participant_state.fx_last_press_ok = False
        return FxFireResponse(fired=False, reason="effects-down", ready_in_seconds=0)
    participant_state.fx_last_press_ok = True
    return FxFireResponse(fired=True, reason="ok", ready_in_seconds=0)
