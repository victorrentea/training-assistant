"""Daemon participant router — identity endpoints (set_name, avatar, location)."""
import logging
import secrets
from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import Response

from railway.shared.names import assign_conference_name
from railway.shared.state import assign_avatar, refresh_avatar as _refresh_avatar_logic, LOTR_NAMES
from daemon.participant.state import participant_state
from daemon.ws_publish import notify_host
from daemon.ws_messages import ParticipantListUpdatedMsg
from daemon.host_state_router import _build_host_participants_list
from daemon.misc.content_files import read_notes_content, read_summary_payload
from daemon.session import state as session_shared_state

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class OkResponse(BaseModel):
    ok: bool = True

class RegisterResponse(BaseModel):
    name: str
    avatar: str

class RenameRequest(BaseModel):
    name: str

class AvatarRequest(BaseModel):
    rejected: list[str] = []

class AvatarResponse(BaseModel):
    ok: bool = True
    avatar: str

class LocationRequest(BaseModel):
    location: str


def _build_qa_for_participant(pid: str) -> list[dict]:
    """Build QA question list (raw format) for participant — is_own/has_upvoted computed client-side."""
    from daemon.qa.state import qa_state
    return qa_state.build_question_list_raw()


def _build_codereview_for_participant(pid: str) -> dict:
    """Build codereview state personalised for participant pid."""
    from daemon.codereview.state import codereview_state
    cr = codereview_state
    result = {
        "snippet": cr.snippet,
        "language": cr.language,
        "phase": cr.phase,
        "confirmed_lines": sorted(cr.confirmed),
        "my_selections": sorted(cr.selections.get(pid, set())),
    }
    # Compute line_percentages in reviewing phase
    if cr.phase == "reviewing" and cr.snippet:
        line_count = len(cr.snippet.splitlines())
        total_participants = max(1, len([
            p for p in cr.selections if not p.startswith("__")
        ]))
        line_percentages: dict[int, int] = {}
        for line_idx in range(line_count):
            sel_count = sum(1 for sels in cr.selections.values() if line_idx in sels)
            line_percentages[line_idx] = round(sel_count * 100 / total_participants)
        result["line_percentages"] = line_percentages
    return result


def _build_debate_for_participant(pid: str) -> dict:
    """Build debate state personalised for participant pid."""
    from daemon.debate.state import debate_state
    ds = debate_state
    snap = ds.snapshot()
    # Add personalised fields
    my_side = ds.sides.get(pid)
    snap["debate_my_side"] = my_side
    my_champion_side = None
    for side, champ_pid in ds.champions.items():
        if champ_pid == pid:
            my_champion_side = side
            break
    snap["debate_my_is_champion"] = my_champion_side is not None
    snap["debate_side_counts"] = {"for": 0, "against": 0}
    for s in ds.sides.values():
        if s in snap["debate_side_counts"]:
            snap["debate_side_counts"][s] += 1
    # Personalise arguments
    snap["arguments"] = [
        {
            **a,
            "is_own": a["author_uuid"] == pid,
            "has_upvoted": pid in a["upvoters"],
        }
        for a in snap["arguments"]
    ]
    return snap


def _build_poll_for_participant(pid: str) -> dict:
    """Build poll state personalised for participant pid."""
    from daemon.poll.state import poll_state
    ps = poll_state
    result: dict = {
        "poll": ps.poll,
        "poll_active": ps.poll_active,
        "vote_counts": ps.vote_counts() if ps.poll else {},
        "poll_timer_seconds": ps.poll_timer_seconds,
        "poll_timer_started_at": ps.poll_timer_started_at.isoformat() if ps.poll_timer_started_at else None,
        "poll_correct_ids": ps.poll_correct_ids,
    }
    # Personalise vote
    my_vote_entry = ps.votes.get(pid)
    if my_vote_entry is not None:
        option_ids = my_vote_entry["option_ids"]
        result["my_vote"] = option_ids[0] if len(option_ids) == 1 else option_ids
        result["my_voted_ids"] = option_ids
    else:
        result["my_vote"] = None
        result["my_voted_ids"] = None
    return result

async def _notify_host_participant_list():
    """Push the current participant list to the host browser directly."""
    await notify_host(
        ParticipantListUpdatedMsg(
            participants=_build_host_participants_list(),
        )
    )


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


@router.post("/register")
async def register_participant(request: Request):
    """Register participant — assign name+avatar. Idempotent for returning participants."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    ps = participant_state

    # Returning participant — return stored identity unchanged
    if pid in ps.participant_names:
        return RegisterResponse(
            name=ps.participant_names[pid],
            avatar=ps.participant_avatars.get(pid, ""),
        )

    # New participant — assign identity
    raw_name: str

    if ps.mode == "conference":
        # Conference mode: auto-assign character name
        fake_state = _build_mini_state()
        char_name, universe = assign_conference_name(fake_state)
        raw_name = char_name
        ps.participant_universes[pid] = universe
    else:
        # Workshop mode: assign next available LOTR name, skip taken ones
        taken_names = set(ps.participant_names.values())
        lotr_name = next((n for n in LOTR_NAMES if n not in taken_names), None)
        raw_name = lotr_name if lotr_name else f"Guest-{secrets.token_hex(3)}"

    ps.participant_names[pid] = raw_name

    # Assign avatar
    fake_state = _build_mini_state()
    avatar = assign_avatar(fake_state, pid, raw_name)
    ps.participant_avatars[pid] = avatar

    # Initialize score
    ps.scores.setdefault(pid, 0)

    await _notify_host_participant_list()

    # Broadcast participant registered event
    request.state.write_back_events = [{
        "type": "participant_registered",
        "participant_id": pid,
        "name": raw_name,
        "avatar": avatar,
        "universe": ps.participant_universes.get(pid, ""),
        "score": ps.scores.get(pid, 0),
        "debate_side": None,
    }]

    return RegisterResponse(name=raw_name, avatar=avatar)


@router.put("/name")
async def rename_participant(request: Request, body: RenameRequest):
    """Rename a registered participant. Returns 400 if not yet registered."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    ps = participant_state

    if pid not in ps.participant_names:
        return JSONResponse({"error": "Participant not registered — call /register first"}, status_code=400)

    raw_name = body.name.strip()[:32]
    if not raw_name:
        return JSONResponse({"error": "Name required"}, status_code=400)

    # Check for duplicate names — reject with 409 if name is taken
    taken = {v for k, v in ps.participant_names.items() if k != pid}
    if raw_name in taken:
        return Response(status_code=409)

    ps.participant_names[pid] = raw_name

    await _notify_host_participant_list()

    request.state.write_back_events = [{
        "type": "participant_renamed",
        "participant_id": pid,
        "name": raw_name,
    }]

    return Response(status_code=200)


@router.post("/avatar")
async def refresh_avatar_endpoint(request: Request, body: AvatarRequest):
    """Re-roll avatar (conference mode only)."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    rejected = set(body.rejected)

    fake_state = _build_mini_state()
    new_avatar = _refresh_avatar_logic(fake_state, pid, rejected)

    if not new_avatar:
        return JSONResponse({"error": "No avatar available"}, status_code=409)

    # Sync back to cache
    participant_state.participant_avatars[pid] = new_avatar
    await _notify_host_participant_list()

    request.state.write_back_events = [{
        "type": "participant_avatar_updated",
        "participant_id": pid,
        "avatar": new_avatar,
    }]

    return AvatarResponse(avatar=new_avatar)


@router.post("/location")
async def set_location(request: Request, body: LocationRequest):
    """Store participant city/timezone."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    loc = body.location.strip()[:80]
    if not loc:
        return JSONResponse({"error": "Location required"}, status_code=400)

    participant_state.locations[pid] = loc

    await _notify_host_participant_list()

    request.state.write_back_events = [{
        "type": "participant_location",
        "participant_id": pid,
        "location": loc,
    }]

    return OkResponse()


@router.get("/state")
async def get_participant_state(request: Request):
    """Return full personalised state for a participant — used on page load and WS reconnect."""
    from daemon.wordcloud.state import wordcloud_state
    from daemon.leaderboard.state import leaderboard_state
    from daemon.misc.state import misc_state

    pid = request.headers.get("x-participant-id", "")
    ps = participant_state

    # Count non-system participants
    participant_count = len([p for p in ps.participant_names if not p.startswith("__")])

    poll_data = _build_poll_for_participant(pid)
    wc = wordcloud_state
    cr = _build_codereview_for_participant(pid)
    debate = _build_debate_for_participant(pid)
    session_id = _get_current_session_id()
    summary = read_summary_payload()
    notes_content = read_notes_content()

    state_msg = {
        "type": "state",
        # Core identity / session
        "mode": ps.mode,
        "my_score": 0 if ps.mode == "conference" else ps.scores.get(pid, 0),
        "my_name": ps.participant_names.get(pid, ""),
        "my_avatar": ps.participant_avatars.get(pid, ""),
        "current_activity": ps.current_activity,
        "participant_count": participant_count,
        "host_connected": True,   # daemon is the host server; if they reached us, host is connected
        "daemon_connected": True,
        # Wordcloud
        "wordcloud_words": wc.words,
        "wordcloud_word_order": wc.word_order,
        "wordcloud_topic": wc.topic,
        # QA (personalised)
        "qa_questions": _build_qa_for_participant(pid),
        # Poll (personalised)
        **poll_data,
        # Codereview (personalised)
        "codereview": cr,
        # Debate (personalised, flattened from snapshot)
        "debate_statement": debate.get("statement"),
        "debate_phase": debate.get("phase"),
        "debate_my_side": debate.get("debate_my_side"),
        "debate_my_is_champion": debate.get("debate_my_is_champion"),
        "debate_side_counts": debate.get("debate_side_counts"),
        "debate_arguments": debate.get("arguments", []),
        "debate_champions": debate.get("champions", {}),
        "debate_auto_assigned": debate.get("auto_assigned", []),
        "debate_first_side": debate.get("first_side"),
        "debate_round_index": debate.get("round_index"),
        "debate_round_timer_seconds": debate.get("round_timer_seconds"),
        "debate_round_timer_started_at": debate.get("round_timer_started_at"),
        # Slides (from misc state — synced from Railway)
        "slides_current": misc_state.slides_current,
        "session_main": misc_state.session_main,
        "session_name": _get_session_name(),
        # Leaderboard
        "leaderboard_data": leaderboard_state.data,
        # Summary / notes
        "summary_points": summary["points"],
        "notes_content": notes_content,
    }

    return JSONResponse(state_msg)


def _get_current_session_id() -> str | None:
    """Safely get the current session ID from session_state module."""
    try:
        from daemon.session_state import get_current_session_id
        return get_current_session_id()
    except Exception:
        return None


def _get_session_name() -> str | None:
    """Return session name from misc cache, with stack fallback."""
    from daemon.misc.state import misc_state
    if misc_state.session_name:
        return misc_state.session_name
    stack = session_shared_state.get_session_stack()
    return stack[-1]["name"] if stack else None
