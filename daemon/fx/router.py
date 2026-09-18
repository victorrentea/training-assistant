"""Daemon FX router — the button the host hands out.

Access is a **grant**, not a secret. The host ticks a participant in the roster;
that participant's UUID goes in `fx_granted_pids`, and their page grows a red
button. Everyone else's page has no button and, more to the point, their POST to
`/fire` is refused — the check lives on the endpoint, because a hidden button is
not a control.

**Why this replaced a secret link.** The old model was a bearer URL: forwardable
by screenshot or chat, firing from anywhere on the internet, and — since the
holder's browser often wasn't the one that joined — frequently unattributable,
which is how "Someone fired the doorbell" ended up in the log twice in a row. A
grant cannot be forwarded by accident (you would have to dig your own UUID out
of localStorage and hand it over deliberately), it is revocable per person, and
every press carries a name by construction.

**What the UUID is worth.** It is 122 bits of `crypto.randomUUID()`, and no
participant-facing frame or endpoint ever carries another participant's — an
invariant the whole product is swept for in
`tests/daemon/test_broadcast_uuid_strip.py::test_no_uuid_in_any_participant_frame`.
It remains a *bearer* credential: whoever can read a grantee's localStorage can
press as them. That is not new — the same UUID already casts their quiz votes —
and the answer is the same as for any other misuse: revoke.

The press itself still takes an **integer** the daemon looked up in the catalog.
No string from a request ever becomes part of a URL on the effects port.
"""
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from daemon import effects_client
from daemon import log as daemon_log
from daemon.participant.state import participant_state

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class FxInfoResponse(BaseModel):
    granted: bool
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
    # ok | not-granted | disabled | cooling | effects-down | no-tile
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


def is_granted(pid: str | None) -> bool:
    """Whether this participant may press the button. The whole access check."""
    return bool(pid) and pid in participant_state.fx_granted_pids


def resolve_caller(pid: str | None) -> tuple[str, bool]:
    """The presser's display name and whether they joined anonymously.

    Same rule as the attention bell (`daemon/attention/router.py`), and for the
    same reason: NEVER fall back to the raw pid. A UUID on the trainer's screen
    once already made it onto a projector, and the FX banner is shown in exactly
    the same room. An unknown or unnamed presser is "Someone" — which, now that
    only granted participants can press, should be vanishingly rare rather than
    the norm it was under the anonymous link.
    """
    if not pid:
        return "Someone", False
    name = (participant_state.participant_names.get(pid) or "").strip() or "Someone"
    return name, pid in participant_state.anonymous_pids


async def _effects_reachable() -> bool:
    """Whether the next press is expected to work — not just whether the apps
    answer a ping.

    A ping and a press are different calls: `/ping` can succeed while the apps
    lack the `/press/<n>` route a press actually needs, and `is_up()` alone
    can't see that. Once a real press has been attempted this session (a
    participant fire or the host's Test button), its outcome overrides the ping
    — until a later attempt succeeds again — so /info never tells a page a
    press would work when the last one just proved otherwise.
    """
    if not await effects_client.is_up():
        return False
    return participant_state.fx_last_press_ok is not False


def cooldown_remaining() -> int:
    """Whole seconds left before the button works again, for anyone.

    Deliberately ONE lever for the whole room rather than a timer per grantee:
    with "grant everyone" a click away, a per-person cooldown would let twenty
    people fire twenty sounds inside one cooldown window. The point of the
    brake is how often the *room* hears it, not how often each person presses.

    Measured on a monotonic clock: a system clock that jumps must not unlock
    the button early or lock it until tomorrow.
    """
    last = participant_state.fx_last_fired_mono
    if last is None:
        return 0
    elapsed = time.monotonic() - last
    remaining = participant_state.fx_cooldown_seconds - elapsed
    return max(0, int(remaining + 0.999)) if remaining > 0 else 0


def _notify_participants_changed() -> None:
    """Tell every participant page that something about FX moved, so it re-reads
    its own `/info`.

    Carries no detail — not who was granted, not who was revoked. It cannot: a
    participant frame that named a UUID would break the invariant this feature's
    whole safety argument rests on. Each page asks about *itself*, over its own
    authenticated call, and learns nothing about anyone else.
    """
    from daemon.ws_messages import FxChangedMsg
    from daemon.ws_publish import broadcast
    broadcast(FxChangedMsg())


# ── Participant router ──

participant_router = APIRouter(prefix="/api/participant/fx", tags=["fx"])


@participant_router.get("/info", response_model=FxInfoResponse)
async def fx_info(request: Request):
    """What one participant's page renders: whether they hold the button, and
    what shape it is in."""
    pid = request.headers.get("x-participant-id")
    n = participant_state.fx_tile_n
    tile = await find_tile(n) or {}
    return FxInfoResponse(
        granted=is_granted(pid),
        tile_n=n,
        label=tile_label(tile) if tile else f"tile {n}",
        effect=tile.get("effect"),
        enabled=participant_state.fx_enabled,
        cooldown_seconds=participant_state.fx_cooldown_seconds,
        ready_in_seconds=cooldown_remaining(),
        effects_up=await _effects_reachable(),
        tile_available=bool(tile),
    )


@participant_router.post("/fire", response_model=FxFireResponse)
async def fx_fire(request: Request):
    """Press the selected tile, if the presser holds the button and all the
    brakes are off."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    # The grant first, before the master switch and before any lookup: someone
    # who was never granted must not be able to tell an armed session from a
    # disarmed one, nor cost the daemon a catalog read by asking.
    if not is_granted(pid):
        return FxFireResponse(fired=False, reason="not-granted", ready_in_seconds=0)

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
    count = participant_state.fx_press_counts.get(pid, 0) + 1
    participant_state.fx_press_counts[pid] = count
    participant_state.persist()

    label = tile_label(tile)
    caller, anonymous = resolve_caller(pid)
    daemon_log.info("host", f"← 🎛️ {caller!r} fired tile {n} ({label}), press #{count}")

    from daemon.ws_messages import FxCoolingMsg, FxFiredMsg
    from daemon.ws_publish import broadcast, notify_host
    await notify_host(FxFiredMsg(tile_n=n, label=label, at=participant_state.fx_last_fired_at,
                                 caller=caller, anonymous=anonymous, uuid=pid, count=count))

    # One lever, so everyone else's button has to grey out too — otherwise the
    # other grantees learn about the cooldown only by pressing into it.
    broadcast(FxCoolingMsg(ready_in_seconds=participant_state.fx_cooldown_seconds))

    # Dual-render, as the attention bell does: the host page flashes its badge,
    # and the trainer's desktop gets a bottom-center tab naming the presser. The
    # badge is the one nobody sees — during a workshop the host panel is behind
    # the slides — and a press the trainer cannot attribute is indistinguishable
    # from his own tablet misfiring. Only the name goes to the overlay; the tile
    # is already playing out loud. Best-effort: the overlay is allowed to be
    # closed, and a missing announcement must never fail a successful press.
    from daemon import addon_bridge_client
    addon_bridge_client.send_fx_fired(caller, anonymous)

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
    tile_n: int
    tile_label: str
    effect: str | None
    cooldown_seconds: int
    last_fired_at: float | None
    effects_up: bool
    # Host-only, so UUIDs are allowed and necessary: the roster draws one
    # toggle and one counter per row, keyed by exactly these.
    granted: list[str]
    press_counts: dict[str, int]


class FxTileRequest(BaseModel):
    n: int


class FxCooldownRequest(BaseModel):
    # Five minutes is already absurd for a party trick; the cap keeps a typo
    # from parking the button for the rest of the workshop.
    seconds: int = Field(ge=0, le=300)


class FxGrantRequest(BaseModel):
    participant_id: str


host_router = APIRouter(prefix="/api/{session_id}/host/fx", tags=["fx"])


async def _state_response() -> FxStateResponse:
    n = participant_state.fx_tile_n
    tile = await find_tile(n) or {}
    return FxStateResponse(
        enabled=participant_state.fx_enabled,
        tile_n=n,
        tile_label=tile_label(tile) if tile else f"tile {n}",
        effect=tile.get("effect"),
        cooldown_seconds=participant_state.fx_cooldown_seconds,
        last_fired_at=participant_state.fx_last_fired_at,
        effects_up=await _effects_reachable(),
        granted=sorted(participant_state.fx_granted_pids),
        press_counts=dict(participant_state.fx_press_counts),
    )


@host_router.get("/state", response_model=FxStateResponse)
async def fx_state():
    """Everything the footer badge, its popover and the roster's toggles render."""
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
    """Arm or disarm every grant at once, without touching who holds one."""
    participant_state.fx_enabled = not participant_state.fx_enabled
    participant_state.persist()
    daemon_log.info("host", f"🎛️ fx {'armed' if participant_state.fx_enabled else 'disarmed'}")
    _notify_participants_changed()
    return await _state_response()


@host_router.post("/grant", response_model=FxStateResponse)
async def fx_grant(body: FxGrantRequest):
    """Hand the button to one participant."""
    participant_state.fx_granted_pids.add(body.participant_id)
    participant_state.persist()
    name, _ = resolve_caller(body.participant_id)
    daemon_log.info("host", f"🎛️ fx granted to {name!r}")
    _notify_participants_changed()
    return await _state_response()


@host_router.post("/revoke", response_model=FxStateResponse)
async def fx_revoke(body: FxGrantRequest):
    """Take it back from one participant.

    Their press count survives: it is the session's record of what happened,
    not a property of the grant, and re-granting someone must not silently
    reset how many times they have already leaned on it.
    """
    participant_state.fx_granted_pids.discard(body.participant_id)
    participant_state.persist()
    name, _ = resolve_caller(body.participant_id)
    daemon_log.info("host", f"🎛️ fx revoked from {name!r}")
    _notify_participants_changed()
    return await _state_response()


@host_router.post("/grant-all", response_model=FxStateResponse)
async def fx_grant_all():
    """Hand the button to the whole roster.

    The roster, not just whoever is online this second: someone who steps out
    and comes back would otherwise find their button gone for reasons nobody
    could explain. The cooldown is what keeps this survivable — see
    `cooldown_remaining`.
    """
    participant_state.fx_granted_pids.update(participant_state.participant_names.keys())
    participant_state.persist()
    daemon_log.info("host", f"🎛️ fx granted to all {len(participant_state.fx_granted_pids)}")
    _notify_participants_changed()
    return await _state_response()


@host_router.post("/revoke-all", response_model=FxStateResponse)
async def fx_revoke_all():
    """Take the button away from everyone — the panic button for the panic button."""
    participant_state.fx_granted_pids.clear()
    participant_state.persist()
    daemon_log.info("host", "🎛️ fx revoked from everyone")
    _notify_participants_changed()
    return await _state_response()


@host_router.post("/tile", response_model=FxStateResponse)
async def fx_set_tile(body: FxTileRequest):
    """Bind the button to a different tile."""
    if await find_tile(body.n) is None:
        raise HTTPException(status_code=404, detail="Unknown tile")
    participant_state.fx_tile_n = body.n
    participant_state.persist()
    daemon_log.info("host", f"🎛️ fx now fires tile {body.n}")
    _notify_participants_changed()
    return await _state_response()


@host_router.post("/cooldown", response_model=FxStateResponse)
async def fx_set_cooldown(body: FxCooldownRequest):
    """Change how often the room may pull the lever."""
    participant_state.fx_cooldown_seconds = body.seconds
    participant_state.persist()
    _notify_participants_changed()
    return await _state_response()


@host_router.post("/test", response_model=FxFireResponse)
async def fx_test():
    """Fire the selected tile from the host page.

    Deliberately ignores every brake: you check the wiring precisely when the
    switch is off and nobody is granted, and a cooldown meant for the room
    should not make the trainer wait. It does not start a cooldown either —
    testing must not take the lever away from the room. It is also not counted
    against anybody: the counters answer "who is leaning on this", and the
    trainer testing his own soundboard is not an answer to that.

    This is also the room's only recovery path once a real press has failed:
    /info trusts the last actual attempt over the ping (see
    _effects_reachable()), so after a failure the participants' buttons stay
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
