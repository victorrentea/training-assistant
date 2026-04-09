"""Daemon participant router — identity endpoints (set_name, roll-avatar, location)."""
import asyncio
import json
import logging
import re
import secrets
import urllib.parse
import urllib.request
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from daemon.host_state_router import _build_host_participants_list
from daemon.misc.content_files import read_notes_content, read_summary_payload
from daemon.participant.state import participant_state
from daemon.session import state as session_shared_state
from daemon.ws_messages import ParticipantListUpdatedMsg
from daemon.ws_publish import notify_host
from railway.shared.names import assign_conference_name
from railway.shared.state import LOTR_NAMES, assign_avatar
from railway.shared.state import refresh_avatar as _refresh_avatar_logic

logger = logging.getLogger(__name__)
_COORDS_RE = re.compile(r"^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$")
_TIMEZONE_RE = re.compile(r"^🕐\s+(.+)$")


# ── Pydantic models ──

class RegisterResponse(BaseModel):
    name: str
    avatar: str

class RenameRequest(BaseModel):
    name: str

class AvatarRequest(BaseModel):
    rejected: list[str] = []

class AvatarResponse(BaseModel):
    avatar: str

class LocationRequest(BaseModel):
    location: str


def _http_get_json(url: str, *, timeout: float = 2.5):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _country_from_coords(lat: str, lon: str) -> str:
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?lat={urllib.parse.quote(lat)}&lon={urllib.parse.quote(lon)}&format=json&addressdetails=1"
    )
    data = _http_get_json(url)
    code = str((data.get("address") or {}).get("country_code") or "").strip().upper()
    return code if len(code) == 2 else ""


def _timezone_from_coords(lat: str, lon: str) -> str:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={urllib.parse.quote(lat)}&longitude={urllib.parse.quote(lon)}&current=temperature_2m"
    )
    data = _http_get_json(url)
    tz = str(data.get("timezone") or "").strip()
    return tz


def _country_from_timezone(tz: str) -> str:
    city_hint = tz.split("/")[-1].replace("_", " ").strip() or tz
    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={urllib.parse.quote(city_hint)}&format=json&limit=1&addressdetails=1"
    )
    rows = _http_get_json(url)
    if not isinstance(rows, list) or not rows:
        return ""
    address = rows[0].get("address") if isinstance(rows[0], dict) else {}
    code = str((address or {}).get("country_code") or "").strip().upper()
    return code if len(code) == 2 else ""


async def _resolve_location_metadata(loc: str) -> tuple[str, str]:
    coord_match = _COORDS_RE.match(loc)
    if coord_match:
        lat = coord_match.group(1)
        lon = coord_match.group(2)
        tz_task = asyncio.to_thread(_timezone_from_coords, lat, lon)
        cc_task = asyncio.to_thread(_country_from_coords, lat, lon)
        tz, country = await asyncio.gather(tz_task, cc_task, return_exceptions=True)
        resolved_tz = "" if isinstance(tz, Exception) else str(tz or "").strip()
        resolved_country = "" if isinstance(country, Exception) else str(country or "").strip().upper()
        return resolved_tz, resolved_country

    tz_match = _TIMEZONE_RE.match(loc)
    if not tz_match:
        return "", ""
    tz = tz_match.group(1).strip()
    country = await asyncio.to_thread(_country_from_timezone, tz)
    return tz, str(country or "").strip().upper()


class QAQuestionRaw(BaseModel):
    id: str
    text: str
    author_uuid: str
    upvoter_uuids: list[str]
    answered: bool
    timestamp: float


class PollOption(BaseModel):
    id: str
    text: str


class PollData(BaseModel):
    id: str
    question: str
    options: list[PollOption]
    multi: bool
    correct_count: int | None = None
    source: str | None = None
    page: str | None = None
    timer_seconds: int | None = None
    timer_started_at: str | None = None
    correct_ids: list[str] | None = None


class CodeReviewParticipantState(BaseModel):
    snippet: str | None = None
    language: str | None = None
    phase: str | None = None
    confirmed_lines: list[int] = []
    my_selections: list[int] = []
    line_percentages: dict[int, int] | None = None


class DebateArgumentParticipant(BaseModel):
    id: str
    author_uuid: str
    side: str
    text: str
    upvoters: list[str]
    ai_generated: bool
    merged_into: str | None = None
    is_own: bool
    has_upvoted: bool


class SlidesCurrentPayload(BaseModel):
    slug: str | None = None
    model_config = ConfigDict(extra="allow")


class SessionMainPayload(BaseModel):
    mode: str | None = None
    model_config = ConfigDict(extra="allow")


class LeaderboardEntry(BaseModel):
    uuid: str
    name: str
    score: int


class LeaderboardData(BaseModel):
    entries: list[LeaderboardEntry]
    total_participants: int


class ParticipantStateResponse(BaseModel):
    type: Literal["state"] = "state"
    mode: str
    my_score: int
    my_name: str
    my_avatar: str
    current_activity: str
    participant_count: int
    host_connected: bool
    daemon_connected: bool
    wordcloud_words: dict[str, int]
    wordcloud_word_order: list[str]
    wordcloud_topic: str
    qa_questions: list[QAQuestionRaw]
    poll: PollData | None = None
    poll_active: bool
    vote_counts: dict[str, int]
    my_vote: str | list[str] | None = None
    my_voted_ids: list[str] | None = None
    codereview: CodeReviewParticipantState
    debate_statement: str | None = None
    debate_phase: str | None = None
    debate_my_side: str | None = None
    debate_my_is_champion: bool
    debate_side_counts: dict[str, int]
    debate_arguments: list[DebateArgumentParticipant]
    debate_champions: dict[str, str]
    debate_auto_assigned: list[str]
    debate_first_side: str | None = None
    debate_round_index: int | None = None
    debate_round_timer_seconds: int | None = None
    debate_round_timer_started_at: str | None = None
    slides_current: SlidesCurrentPayload | None = None
    session_main: SessionMainPayload | None = None
    session_name: str | None = None
    leaderboard_data: LeaderboardData | None = None
    summary_count: int
    notes_count: int


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
    poll = dict(ps.poll) if ps.poll else None
    if poll is not None:
        poll["timer_seconds"] = ps.poll_timer_seconds
        poll["timer_started_at"] = (
            ps.poll_timer_started_at.isoformat() if ps.poll_timer_started_at else None
        )
        poll["correct_ids"] = ps.poll_correct_ids

    result: dict = {
        "poll": poll,
        "poll_active": ps.poll_active,
        "vote_counts": ps.vote_counts() if ps.poll else {},
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
        participants={uid: None for uid in ps.participant_names},  # fake WS entries for name pool checks
        mode=ps.mode,
    )


@router.post("/register", response_model=RegisterResponse)
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


@router.put("/name", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
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

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/roll-avatar", response_model=AvatarResponse)
async def roll_avatar_endpoint(request: Request, body: AvatarRequest):
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


@router.post("/location", status_code=204)
async def set_location(request: Request, body: LocationRequest):
    """Store participant city/timezone."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    loc = body.location.strip()[:80]
    if not loc:
        return JSONResponse({"error": "Location required"}, status_code=400)

    participant_state.locations[pid] = loc
    tz, country = await _resolve_location_metadata(loc)
    if tz:
        participant_state.location_timezones[pid] = tz
    else:
        participant_state.location_timezones.pop(pid, None)
    if country:
        participant_state.location_countries[pid] = country
    else:
        participant_state.location_countries.pop(pid, None)

    await _notify_host_participant_list()

    request.state.write_back_events = [{
        "type": "participant_location",
        "participant_id": pid,
        "location": loc,
        "location_tz": tz,
        "location_country": country,
    }]

    return Response(status_code=204)


@router.get("/state", response_model=ParticipantStateResponse)
async def get_participant_state(request: Request):
    """Return full personalised state for a participant — used on page load and WS reconnect."""
    from daemon.leaderboard.state import leaderboard_state
    from daemon.misc.state import misc_state
    from daemon.wordcloud.state import wordcloud_state

    pid = request.headers.get("x-participant-id", "")
    ps = participant_state

    # Count only active connected non-system participants.
    participant_count = len([p for p in ps.online_participants if not p.startswith("__")])

    poll_data = _build_poll_for_participant(pid)
    wc = wordcloud_state
    cr = _build_codereview_for_participant(pid)
    debate = _build_debate_for_participant(pid)
    summary = read_summary_payload()
    notes_content = read_notes_content()
    notes_count = sum(1 for line in (notes_content or "").splitlines() if line.strip())

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
        # Summary / notes (counts only — full content fetched on demand)
        "summary_count": len(summary["points"]),
        "notes_count": notes_count,
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
