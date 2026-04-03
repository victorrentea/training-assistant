"""Daemon participant router — identity endpoints (set_name, avatar, location)."""
import logging
import secrets
from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.names import assign_conference_name
from core.state import assign_avatar, refresh_avatar as _refresh_avatar_logic, LOTR_NAMES
from daemon.participant.state import participant_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/participant", tags=["participant"])


def _build_mini_state() -> SimpleNamespace:
    """Build an AppState-like facade from our local cache for avatar/name functions.

    The core.state functions (assign_avatar, refresh_avatar, assign_conference_name)
    expect an object with participant_names, participant_avatars, participants, etc.
    We use SimpleNamespace to avoid depending on AppState.__init__.

    Note: `participants` is populated from `participant_names.keys()` so that
    assign_conference_name() correctly sees all known participants (it uses
    `state.participants` to determine which names are in use).
    """
    ps = participant_state
    return SimpleNamespace(
        participant_names=ps.participant_names,
        participant_avatars=ps.participant_avatars,
        participant_universes=ps.participant_universes,
        participants={uid: None for uid in ps.participant_names},  # fake WS entries for name pool checks
        mode=ps.mode,
    )


@router.post("/name")
async def set_name(request: Request):
    """Register or rename a participant."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    raw_name = str(body.get("name", "")).strip()[:32]

    ps = participant_state

    # Returning participant — fast path (matches Railway WS behavior: any set_name
    # from a known UUID restores existing identity without re-validation)
    if pid in ps.participant_names:
        return JSONResponse({
            "ok": True,
            "returning": True,
            "name": ps.participant_names[pid],
            "avatar": ps.participant_avatars.get(pid, ""),
        })

    # Conference mode with empty name → auto-assign character name
    if ps.mode == "conference" and not raw_name:
        fake_state = _build_mini_state()
        char_name, universe = assign_conference_name(fake_state)
        raw_name = char_name
        ps.participant_universes[pid] = universe

    if not raw_name:
        return JSONResponse({"error": "Name required"}, status_code=400)

    # Check for duplicate names (race guard)
    taken = {v for k, v in ps.participant_names.items() if k != pid}
    if raw_name in taken:
        # Try to suggest alternative
        available = [n for n in LOTR_NAMES if n not in taken]
        raw_name = available[0] if available else f"Guest{secrets.randbelow(900) + 100}"

    ps.participant_names[pid] = raw_name

    # Assign avatar
    fake_state = _build_mini_state()
    avatar = assign_avatar(fake_state, pid, raw_name)
    # Sync back to our cache
    ps.participant_avatars[pid] = avatar

    # Initialize score
    ps.scores.setdefault(pid, 0)

    # Debate late-joiner auto-assign
    debate_side = None
    if (ps.debate_phase
            and ps.debate_phase != "side_selection"
            and pid not in ps.debate_sides):
        for_count = sum(1 for s in ps.debate_sides.values() if s == "for")
        against_count = sum(1 for s in ps.debate_sides.values() if s == "against")
        side = "for" if for_count <= against_count else "against"
        ps.debate_sides[pid] = side
        debate_side = side
        logger.info("Late joiner %s auto-assigned to %s", raw_name, side)

    # Build write-back event (sent by proxy_handler BEFORE proxy_response)
    request.state.write_back_events = [{
        "type": "participant_registered",
        "participant_id": pid,
        "name": raw_name,
        "avatar": avatar,
        "universe": ps.participant_universes.get(pid, ""),
        "score": ps.scores.get(pid, 0),
        "debate_side": debate_side,
    }]

    return JSONResponse({"ok": True, "name": raw_name, "avatar": avatar})


@router.post("/avatar")
async def refresh_avatar_endpoint(request: Request):
    """Re-roll avatar (conference mode only)."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    rejected = set(body.get("rejected", []))

    fake_state = _build_mini_state()
    new_avatar = _refresh_avatar_logic(fake_state, pid, rejected)

    if not new_avatar:
        return JSONResponse({"error": "No avatar available"}, status_code=409)

    # Sync back to cache
    participant_state.participant_avatars[pid] = new_avatar

    request.state.write_back_events = [{
        "type": "participant_avatar_updated",
        "participant_id": pid,
        "avatar": new_avatar,
    }]

    return JSONResponse({"ok": True, "avatar": new_avatar})


@router.post("/location")
async def set_location(request: Request):
    """Store participant city/timezone."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    loc = str(body.get("location", "")).strip()[:80]
    if not loc:
        return JSONResponse({"error": "Location required"}, status_code=400)

    participant_state.locations[pid] = loc

    request.state.write_back_events = [{
        "type": "participant_location",
        "participant_id": pid,
        "location": loc,
    }]

    return JSONResponse({"ok": True})
