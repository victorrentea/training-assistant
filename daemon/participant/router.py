"""Daemon participant router — identity endpoints (set_name, roll-avatar, location)."""
import asyncio
import json
import logging
import random
import re
import secrets
import ssl
import urllib.parse
import urllib.request
from types import SimpleNamespace

import certifi
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import Response

from daemon.host_state_router import _build_host_participants_list
from daemon.misc.content_files import read_notes_updated_at, read_summary_payload
from daemon.participant.state import GitRepoActivity, participant_state
from daemon.ws_messages import ParticipantListUpdatedMsg
from daemon.ws_publish import notify_host
from railway.shared.names import assign_conference_name
from railway.shared.state import LOTR_NAMES, get_avatar_filename
from railway.shared.state import refresh_avatar as _refresh_avatar_logic

logger = logging.getLogger(__name__)
_COORDS_RE = re.compile(r"^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$")
_TIMEZONE_RE = re.compile(r"^🕐\s+(.+)$")


# ── Pydantic models ──

class RegisterResponse(BaseModel):
    name: str
    avatar: str


class RegisterRequest(BaseModel):
    name: str | None = None
    location: str | None = None


class RenameRequest(BaseModel):
    name: str

class AvatarRequest(BaseModel):
    rejected: list[str] = []

class AvatarResponse(BaseModel):
    avatar: str

class LocationRequest(BaseModel):
    location: str


class GitActivityResponse(BaseModel):
    git_repos: list[GitRepoActivity]


class SlideHistoryResponse(BaseModel):
    slides: list[dict]


def _http_get_json(url: str, *, timeout: float = 2.5):
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "TrainingAssistant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
        return json.loads(response.read().decode("utf-8"))


def _country_from_coords(lat: str, lon: str) -> tuple[str, str]:
    """Return (country_code, city_name) from reverse geocoding."""
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?lat={urllib.parse.quote(lat)}&lon={urllib.parse.quote(lon)}&format=json&addressdetails=1"
    )
    data = _http_get_json(url)
    address = data.get("address") or {}
    code = str(address.get("country_code") or "").strip().upper()
    city = str(
        address.get("city") or address.get("town") or address.get("village")
        or address.get("county") or address.get("suburb") or address.get("state") or ""
    ).strip()
    return (code if len(code) == 2 else ""), city


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


async def _resolve_location_metadata(loc: str) -> tuple[str, str, str]:
    """Return (tz, country_code, city_name). city_name is non-empty only for lat/lon inputs."""
    coord_match = _COORDS_RE.match(loc)
    if coord_match:
        lat = coord_match.group(1)
        lon = coord_match.group(2)
        tz_task = asyncio.to_thread(_timezone_from_coords, lat, lon)
        cc_task = asyncio.to_thread(_country_from_coords, lat, lon)
        tz, country_city = await asyncio.gather(tz_task, cc_task, return_exceptions=True)
        resolved_tz = "" if isinstance(tz, Exception) else str(tz or "").strip()
        if isinstance(country_city, Exception):
            resolved_country, resolved_city = "", ""
        else:
            resolved_country, resolved_city = country_city  # type: ignore[misc]
            resolved_country = str(resolved_country or "").strip().upper()
        return resolved_tz, resolved_country, resolved_city

    tz_match = _TIMEZONE_RE.match(loc)
    if not tz_match:
        return "", "", ""
    tz = tz_match.group(1).strip()
    country = await asyncio.to_thread(_country_from_timezone, tz)
    return tz, str(country or "").strip().upper(), ""


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
    page: int | None = None


class WordcloudData(BaseModel):
    words: dict[str, int]
    word_order: list[str]
    topic: str


class DebateData(BaseModel):
    statement: str | None = None
    phase: str | None = None
    my_side: str | None = None
    my_is_champion: bool
    side_counts: dict[str, int]
    arguments: list[DebateArgumentParticipant]
    champions: dict[str, str]
    auto_assigned: list[str]
    first_side: str | None = None
    round_index: int | None = None
    round_timer_seconds: int | None = None
    round_timer_started_at: str | None = None


class ParticipantStateResponse(BaseModel):
    mode: str
    my_score: int
    my_name: str
    my_avatar: str
    current_activity: str
    session_name: str | None = None
    wordcloud: WordcloudData
    qa_questions: list[QAQuestionRaw]
    poll: PollData | None = None
    poll_active: bool
    vote_counts: dict[str, int]
    my_voted_ids: list[str] | None = None
    codereview: CodeReviewParticipantState
    debate: DebateData
    slides_current: SlidesCurrentPayload | None = None
    talk_presentation_slug: str | None = None
    notes_updated_at: str | None = None
    summary_updated_at: str | None = None
    slides_history_count: int
    gdrive_url: str | None = None
    has_agenda: bool = False


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


def _get_score(pid: str) -> int:
    """Read score from the authoritative daemon.scores singleton."""
    from daemon.scores import scores
    return scores.scores.get(pid, 0)


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


def _pick_random_available_avatar(pid: str) -> str:
    """Pick a random avatar, preferring ones unused by other participants in session."""
    ps = participant_state
    taken_by_others = {
        avatar
        for uid, avatar in ps.participant_avatars.items()
        if uid != pid and not uid.startswith("__")
    }
    all_avatars = [get_avatar_filename(name) for name in LOTR_NAMES]
    available = [avatar for avatar in all_avatars if avatar not in taken_by_others]
    if not available:
        available = all_avatars
    return random.choice(available)


@router.post("/rejoin", response_model=RegisterResponse)
async def rejoin_participant(request: Request):
    """Lookup-only identity restore for returning UUIDs in current session."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    ps = participant_state
    if pid not in ps.participant_names:
        return JSONResponse({"error": "Participant not found in current session"}, status_code=404)

    return RegisterResponse(
        name=ps.participant_names[pid],
        avatar=ps.participant_avatars.get(pid, ""),
    )


@router.post("/register", response_model=RegisterResponse)
async def register_participant(request: Request, body: RegisterRequest):
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
    explicit_name = (body.name or "").strip()[:32]

    if explicit_name:
        taken = {v for k, v in ps.participant_names.items() if k != pid}
        if explicit_name in taken:
            return Response(status_code=409)
        raw_name = explicit_name
    elif ps.mode == "talk":
        # Conference mode: auto-assign character name
        fake_state = _build_mini_state()
        char_name, universe = assign_conference_name(fake_state)
        raw_name = char_name
        ps.participant_universes[pid] = universe
    else:
        # Workshop mode: random LOTR name while trying to keep name/avatar in sync
        taken_names = set(ps.participant_names.values())
        taken_avatars = {a for uid, a in ps.participant_avatars.items() if uid != pid and not uid.startswith("__")}
        sync_candidates = [
            name for name in LOTR_NAMES
            if name not in taken_names and get_avatar_filename(name) not in taken_avatars
        ]
        if sync_candidates:
            raw_name = random.choice(sync_candidates)
        else:
            remaining = [name for name in LOTR_NAMES if name not in taken_names]
            raw_name = random.choice(remaining) if remaining else f"Guest-{secrets.token_hex(3)}"

    ps.participant_names[pid] = raw_name

    # Avatar rules:
    # - explicit name path: random available avatar across session participants
    # - random workshop path: keep name/avatar synced when the chosen LOTR avatar is available
    if explicit_name:
        avatar = _pick_random_available_avatar(pid)
    else:
        mapped_avatar = get_avatar_filename(raw_name) if raw_name in LOTR_NAMES else None
        taken_by_others = {a for uid, a in ps.participant_avatars.items() if uid != pid and not uid.startswith("__")}
        if mapped_avatar and mapped_avatar not in taken_by_others:
            avatar = mapped_avatar
        else:
            avatar = _pick_random_available_avatar(pid)
    ps.participant_avatars[pid] = avatar

    # Initialize score
    ps.scores.setdefault(pid, 0)

    # Store location if provided at registration time
    if body.location:
        loc = body.location.strip()[:80]
        if loc:
            ps.locations[pid] = loc
            tz, country, city = await _resolve_location_metadata(loc)
            display_loc = city if city else loc
            ps.locations[pid] = display_loc
            if tz:
                ps.location_timezones[pid] = tz
            else:
                ps.location_timezones.pop(pid, None)
            if country:
                ps.location_countries[pid] = country
            else:
                ps.location_countries.pop(pid, None)

    await _notify_host_participant_list()

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

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/roll-avatar", response_model=AvatarResponse)
async def roll_avatar_endpoint(request: Request, body: AvatarRequest):
    """Re-roll avatar (conference mode only)."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    rejected = set(body.rejected)

    fake_state = _build_mini_state()
    new_avatar = _refresh_avatar_logic(fake_state, pid, rejected)  # type: ignore[arg-type]

    if not new_avatar:
        return JSONResponse({"error": "No avatar available"}, status_code=409)

    # Sync back to cache
    participant_state.participant_avatars[pid] = new_avatar
    await _notify_host_participant_list()

    return AvatarResponse(avatar=new_avatar)


@router.put("/location", status_code=204)
async def set_location(request: Request, body: LocationRequest):
    """Store participant city/timezone."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    loc = body.location.strip()[:80]
    if not loc:
        return JSONResponse({"error": "Location required"}, status_code=400)

    participant_state.locations[pid] = loc
    tz, country, city = await _resolve_location_metadata(loc)
    display_loc = city if city else loc
    participant_state.locations[pid] = display_loc
    if tz:
        participant_state.location_timezones[pid] = tz
    else:
        participant_state.location_timezones.pop(pid, None)
    if country:
        participant_state.location_countries[pid] = country
    else:
        participant_state.location_countries.pop(pid, None)

    await _notify_host_participant_list()

    return Response(status_code=204)


@router.get("/state", response_model=ParticipantStateResponse)
async def get_participant_state(request: Request):
    """Return full personalised state for a participant — used on page load and WS reconnect."""
    from daemon.misc.state import misc_state
    from daemon.wordcloud.state import wordcloud_state

    pid = request.headers.get("x-participant-id", "")
    ps = participant_state

    poll_data = _build_poll_for_participant(pid)
    wc = wordcloud_state
    cr = _build_codereview_for_participant(pid)
    debate = _build_debate_for_participant(pid)
    summary = read_summary_payload()
    notes_updated_at = read_notes_updated_at()

    from daemon.session.state import get_active_session_name
    state_msg = {
        # Core identity / session
        "mode": ps.mode,
        "my_score": 0 if ps.mode == "talk" else _get_score(pid),
        "my_name": ps.participant_names.get(pid, ""),
        "my_avatar": ps.participant_avatars.get(pid, ""),
        "current_activity": ps.current_activity,
        "session_name": get_active_session_name(),
        # Wordcloud
        "wordcloud": {
            "words": wc.words,
            "word_order": wc.word_order,
            "topic": wc.topic,
        },
        # QA (personalised)
        "qa_questions": _build_qa_for_participant(pid),
        # Poll (personalised)
        **poll_data,
        # Codereview (personalised)
        "codereview": cr,
        # Debate (personalised, grouped)
        "debate": {
            "statement": debate.get("statement"),
            "phase": debate.get("phase"),
            "my_side": debate.get("debate_my_side"),
            "my_is_champion": debate.get("debate_my_is_champion"),
            "side_counts": debate.get("debate_side_counts"),
            "arguments": debate.get("arguments", []),
            "champions": debate.get("champions", {}),
            "auto_assigned": debate.get("auto_assigned", []),
            "first_side": debate.get("first_side"),
            "round_index": debate.get("round_index"),
            "round_timer_seconds": debate.get("round_timer_seconds"),
            "round_timer_started_at": debate.get("round_timer_started_at"),
        },
        # Emoji counters (talk mode)
        "emoji_counters": dict(ps.emoji_counters),
        # Slides (from misc state — synced from Railway)
        "slides_current": misc_state.slides_current,
        "talk_presentation_slug": misc_state.talk_presentation_slug,
        # Summary / notes (timestamps only — full content fetched on demand)
        "notes_updated_at": notes_updated_at,
        "summary_updated_at": summary["updated_at"],
        "slides_history_count": len(misc_state.slides_viewed),
        # Google Drive folder link for session materials
        "gdrive_url": misc_state.gdrive_url,
        # Agenda .docx availability
        "has_agenda": misc_state.agenda_docx_path is not None and misc_state.agenda_docx_path.exists(),
        # Last git repo URL — used by talk mode to enable the Git Repo top button
        "last_git_url": ps.git_repos[-1].url if ps.git_repos else None,
    }

    return JSONResponse(state_msg)


@router.get("/git-activity", response_model=GitActivityResponse)
async def get_git_activity():
    """Return accumulated git file-open activity for the current session."""
    return GitActivityResponse(git_repos=participant_state.git_repos)


def _get_current_session_id() -> str | None:
    """Safely get the current session ID from session_state module."""
    try:
        from daemon.session_state import get_current_session_id
        return get_current_session_id()
    except Exception:
        return None


@router.get("/slide-history", response_model=SlideHistoryResponse)
async def get_slide_history():
    """Return accumulated per-slide viewing history for the current session."""
    from daemon.misc.state import misc_state
    return SlideHistoryResponse(slides=misc_state.slides_viewed)


# ── Host-only router ──

host_router = APIRouter(prefix="/api/{session_id}/host", tags=["participant"])


@host_router.post("/participants/resolve-locations", status_code=204)
async def resolve_participant_locations(session_id: str):
    """Backfill city name + timezone + country for all participants missing geo metadata."""
    from daemon import log as _log

    ps = participant_state

    async def _resolve_coords(pid: str, loc: str) -> None:
        try:
            tz, country, city = await _resolve_location_metadata(loc)
        except Exception as exc:
            _log.error("participant", f"resolve-locations failed for {pid}: {exc}")
            return
        if city:
            ps.locations[pid] = city
        if tz:
            ps.location_timezones[pid] = tz
        else:
            ps.location_timezones.pop(pid, None)
        if country:
            ps.location_countries[pid] = country
        else:
            ps.location_countries.pop(pid, None)

    async def _resolve_country_from_tz(pid: str, tz: str) -> None:
        try:
            country = await asyncio.to_thread(_country_from_timezone, tz)
        except Exception as exc:
            _log.error("participant", f"resolve-country failed for {pid}: {exc}")
            return
        if country:
            ps.location_countries[pid] = country

    tasks = []
    for pid, loc in list(ps.locations.items()):
        loc = str(loc or "").strip()
        if _COORDS_RE.match(loc):
            tasks.append(_resolve_coords(pid, loc))
        elif ps.location_timezones.get(pid) and not ps.location_countries.get(pid):
            tasks.append(_resolve_country_from_tz(pid, ps.location_timezones[pid]))

    if tasks:
        await asyncio.gather(*tasks)
        await _notify_host_participant_list()
    return Response(status_code=204)
