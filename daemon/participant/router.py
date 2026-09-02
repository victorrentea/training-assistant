"""Daemon participant router — identity endpoints (set_name, roll-avatar, location)."""

import asyncio
import json
import logging
import random
import re
import secrets
import ssl
import time
import urllib.parse
import urllib.request
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import certifi
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.responses import Response

from daemon.emoji.catalog import EMOJI_CATALOG, EmojiDef
from daemon.host_state_router import _build_host_participants_list
from daemon.misc.content_files import read_notes_updated_at, read_summary_payload
from daemon.participant.names import (
    LOTR_NAMES,
    assign_conference_name,
    get_avatar_filename,
)
from daemon.participant.names import (
    refresh_avatar as _refresh_avatar_logic,
)
from daemon.participant.purge import PurgeReport
from daemon.participant.sanitize import (
    MAX_NAME_LEN as _MAX_NAME_LEN_SHARED,
)
from daemon.participant.sanitize import (
    RESERVED_TRAINER_NAME,
    is_reserved_trainer_name,
    normalize_for_dedup,
    sanitize_name,
)
from daemon.participant.state import participant_state
from daemon.session import state as session_shared_state
from daemon.slides.models import CurrentSlide
from daemon.ws_messages import (
    ParticipantListUpdatedMsg,
    ParticipantNamesUpdatedMsg,
    ScoresUpdatedMsg,
)
from daemon.ws_publish import broadcast, notify_host

logger = logging.getLogger(__name__)
# Server-side cap on participant display names; mirrored by maxlength="64" on
# the participant page's three name inputs. Sourced from the shared sanitizer so
# the cap and the sanitization pipeline can never drift.
_MAX_NAME_LEN = _MAX_NAME_LEN_SHARED
_COORDS_RE = re.compile(r"^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$")
_TIMEZONE_RE = re.compile(r"^🕐\s+(.+)$")


# ── Pydantic models ──


class RegisterResponse(BaseModel):
    name: str
    avatar: str
    # Soft, non-blocking duplicate flag: true iff an explicitly-typed name
    # collided with another participant at write time. NEVER a 409.
    name_conflict: bool = False


class RegisterRequest(BaseModel):
    name: str | None = None
    location: str | None = None


class RenameRequest(BaseModel):
    name: str


class RenameResponse(BaseModel):
    # PUT /name returns 200 + this body (symmetric with register) instead of a
    # bare 204, so the client can read the soft duplicate flag. NEVER a 409.
    name_conflict: bool = False


class AvatarRequest(BaseModel):
    rejected: list[str] = []


class AvatarResponse(BaseModel):
    avatar: str


class LocationRequest(BaseModel):
    location: str


_KNOWN_VIEWS = {
    "activity",
    "slides",
    "summary",
    "notes",
    "agenda",
    "report-bug",
    "upload-paste",
    "files",
}


class ViewEngagementDelta(BaseModel):
    seconds: int = Field(0, ge=0)
    visits: int = Field(0, ge=0)
    clicks: int = Field(0, ge=0)


class ActivityReportRequest(BaseModel):
    current_view: str = ""
    deltas: dict[str, ViewEngagementDelta] = {}


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
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
        or address.get("suburb")
        or address.get("state")
        or ""
    ).strip()
    return (code if len(code) == 2 else ""), city


def _timezone_from_coords(lat: str, lon: str) -> str:
    # Without timezone=auto, Open-Meteo always returns "GMT" for the timezone field.
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={urllib.parse.quote(lat)}&longitude={urllib.parse.quote(lon)}"
        "&current=temperature_2m&timezone=auto"
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


def _apply_browser_tz(pid: str, tz_raw: str | None) -> bool:
    """Store browser-reported IANA timezone for pid. Returns True if the stored value changed."""
    if not tz_raw:
        return False
    tz = str(tz_raw).strip()[:64]
    if not tz:
        return False
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    if participant_state.location_timezones.get(pid) == tz:
        return False
    participant_state.location_timezones[pid] = tz
    return True


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


class QAQuestionParticipant(BaseModel):
    """UUID-free Q&A item for the participant /state snapshot.

    SECURITY: carries no author/upvoter UUIDs. The two personalised booleans are
    resolved server-side from the requesting participant's own pid, so the wire
    never exposes anyone's identity.
    """
    id: str
    text: str
    upvote_count: int
    answered: bool
    timestamp: float
    is_own: bool
    has_upvoted: bool


class QuizData(BaseModel):
    id: str
    question: str
    options: list[str]
    multi: bool
    correct_count: int | None = None
    end_timer_seconds: int | None = None
    end_timer_started_at: str | None = None
    correct_indices: list[int] | None = None


class CodeReviewParticipantState(BaseModel):
    snippet: str | None = None
    language: str | None = None
    phase: str | None = None
    confirmed_lines: list[int] = []
    my_selections: list[int] = []
    line_percentages: dict[int, int] | None = None


class DebateArgumentParticipant(BaseModel):
    """UUID-free debate argument for the participant /state snapshot."""
    id: str
    side: str
    text: str
    upvote_count: int
    ai_generated: bool
    merged_into: str | None = None
    is_own: bool
    has_upvoted: bool


class WordcloudData(BaseModel):
    words: dict[str, int]
    word_order: list[str]
    topic: str


class DebateData(BaseModel):
    """UUID-free personalised debate state for the participant /state snapshot.

    SECURITY: champions is side→bool (not side→uuid); the auto_assigned uuid list
    is replaced by the per-viewer my_auto_assigned flag; arguments are UUID-free.
    """
    statement: str | None = None
    phase: str | None = None
    my_side: str | None = None
    my_is_champion: bool
    my_auto_assigned: bool = False
    side_counts: dict[str, int]
    arguments: list[DebateArgumentParticipant]
    champions: dict[str, bool]
    first_side: str | None = None
    round_index: int | None = None
    round_timer_seconds: int | None = None
    round_timer_started_at: str | None = None


class ParticipantStateResponse(BaseModel):
    mode: str
    my_score: int
    # Opaque, non-identifying token this participant is keyed by in the
    # scores_updated broadcast — lets the client pick out its own live score
    # without any UUID on the wire. See daemon.scores.score_token.
    my_score_token: str
    my_name: str
    my_avatar: str
    current_activity: str
    session_name: str | None = None
    # Roster display NAMES only (UUID-free) so the client can compute the
    # in-session duplicate indicator immediately on load, before the first
    # participant_names_updated broadcast arrives.
    participant_names: list[str] = []
    wordcloud: WordcloudData
    qa_questions: list[QAQuestionParticipant]
    quiz: QuizData | None = None
    quiz_active: bool
    my_voted_indices: list[int] | None = None
    quiz_correct_indices: list[int] | None = None
    poll: dict[str, Any] | None = None
    poll_active: bool = False
    my_poll_voted_indices: list[int] | None = None
    poll_vote_counts: list[int] | None = None
    codereview: CodeReviewParticipantState
    debate: DebateData
    slides_current: CurrentSlide | None = None
    talk_presentation_slug: str | None = None
    notes_updated_at: str | None = None
    summary_updated_at: str | None = None
    slides_history_count: int
    files_count: int = 0
    prompts_count: int = 0
    gdrive_url: str | None = None
    feedback_url: str | None = None
    has_agenda: bool = False
    emoji_catalog: list[EmojiDef]
    # Attention master switch — drives the bell button + notification affordance.
    attention_enabled: bool = False


def _files_count() -> int:
    """Number of files opened in the active session (0 if none)."""
    from daemon import files_md
    from daemon.misc.content_files import get_active_session_folder

    return files_md.count_open_files(get_active_session_folder())


def _prompts_count() -> int:
    """Number of agent prompts intercepted in the active session (0 if none)."""
    from daemon.misc.content_files import read_prompts

    return len(read_prompts())


def _build_qa_for_participant(pid: str) -> list[dict]:
    """Build the UUID-free Q&A list for participant pid (is_own/has_upvoted resolved here)."""
    from daemon.qa.state import qa_state

    return qa_state.build_question_list_for_participant(pid)


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
        total_participants = max(1, len([p for p in cr.selections if not p.startswith("__")]))
        line_percentages: dict[int, int] = {}
        for line_idx in range(line_count):
            sel_count = sum(1 for sels in cr.selections.values() if line_idx in sels)
            line_percentages[line_idx] = round(sel_count * 100 / total_participants)
        result["line_percentages"] = line_percentages
    return result


def _build_debate_for_participant(pid: str) -> dict:
    """Build the UUID-free, personalised debate state for participant pid.

    Shared fields come from the UUID-free public_snapshot(); the per-viewer facts
    (my_side / my_is_champion / my_auto_assigned and each argument's is_own /
    has_upvoted) are resolved here from the raw state using this participant's own
    pid — the returned dict never contains anyone's UUID.
    """
    from daemon.debate.state import debate_state

    ds = debate_state
    snap = ds.public_snapshot()
    # public_snapshot() built its arguments from ds.arguments in order — zip the
    # raw entries back in to resolve the two per-viewer booleans.
    snap["arguments"] = [
        {
            **public,
            "is_own": raw["author_uuid"] == pid,
            "has_upvoted": pid in raw["upvoters"],
        }
        for public, raw in zip(snap["arguments"], ds.arguments)
    ]
    snap["my_side"] = ds.sides.get(pid)
    snap["my_is_champion"] = pid in ds.champions.values()
    snap["my_auto_assigned"] = pid in ds.auto_assigned
    return snap


def _get_score(pid: str) -> int:
    """Read score from the authoritative daemon.scores singleton."""
    from daemon.scores import scores

    return scores.scores.get(pid, 0)


def _score_token(pid: str) -> str:
    """This participant's opaque, non-identifying score-broadcast token."""
    from daemon.scores import score_token

    return score_token(pid)


def _build_quiz_for_participant(pid: str) -> dict:
    """Build quiz state personalised for participant pid."""
    from daemon.quiz.state import quiz_state

    ps = quiz_state
    quiz = dict(ps.quiz) if ps.quiz else None
    if quiz is not None:
        quiz["end_timer_seconds"] = ps.quiz_timer_seconds
        quiz["end_timer_started_at"] = (
            ps.quiz_timer_started_at.isoformat() if ps.quiz_timer_started_at else None
        )
        quiz["correct_indices"] = ps.quiz_correct_indices

    result: dict = {
        "quiz": quiz,
        "quiz_active": ps.quiz_active,
    }
    my_vote_entry = ps.votes.get(pid)
    if my_vote_entry is not None:
        result["my_voted_indices"] = my_vote_entry["option_indices"]
    else:
        result["my_voted_indices"] = None
    result["quiz_correct_indices"] = ps.quiz_correct_indices
    return result


def _build_poll_for_participant(pid: str) -> dict:
    """Build poll state personalised for participant pid.

    Returns the public snapshot, this participant's own vote (never others'),
    and the aggregate counts when the poll is public OR ended (stopped but
    not yet cleared — results are visible read-only).
    """
    from daemon.poll.state import poll_state

    if poll_state.data is None:
        return {
            "poll": None,
            "poll_active": False,
            "poll_ended": False,
            "my_poll_voted_indices": None,
            "poll_vote_counts": None,
        }

    snapshot = {
        "question": poll_state.data.question,
        "options": list(poll_state.data.options),
        "multi": poll_state.data.multi,
        "public": poll_state.data.public,
    }
    my_entry = poll_state.votes.get(pid)
    ended = poll_state.ended_at is not None
    counts = poll_state.vote_counts() if (poll_state.data.public or ended) else None
    return {
        "poll": snapshot,
        "poll_active": poll_state.started,
        "poll_ended": ended,
        "my_poll_voted_indices": my_entry["option_indices"] if my_entry else None,
        "poll_vote_counts": counts,
    }


def _participant_display_names() -> list[str]:
    """Roster display names only — the UUID-free payload for participants.

    SECURITY: names only, never UUIDs or any stable per-user id. A participant's
    identity is their X-Participant-ID UUID; leaking it enables impersonation.
    Reads the name dict directly (same filtering as the host enumerator: skip
    internal __ ids and blank names) without building the full host payload.
    """
    return [
        name
        for pid, name in participant_state.participant_names.items()
        if not pid.startswith("__") and str(name).strip()
    ]


def _is_name_taken(pid: str, name: str) -> bool:
    """True iff another participant already holds `name` (soft-conflict check).

    Compares on the normalized dedup key (casefold + NFC + collapsed whitespace)
    so `Alice`/`alice`, NFC-vs-NFD `José` and double-space variants all count as
    collisions — matching the client's post-sanitization view of a name.
    """
    target = normalize_for_dedup(name)
    if not target:
        return False
    return any(
        other_pid != pid and normalize_for_dedup(other_name) == target
        for other_pid, other_name in participant_state.participant_names.items()
    )


def _regenerate_attendees() -> None:
    """Fully regenerate the live attendees.md from the roster (best-effort)."""
    try:
        from daemon import attendees_md

        attendees_md.regenerate_attendees()
    except Exception as exc:  # never let attendance-sheet I/O break a join/rename
        logger.warning("attendees.md regeneration failed: %s", exc)


def _publish_names_if_changed() -> None:
    """On a real name-set change: broadcast the UUID-free names + regen attendees.md.

    Both side effects derive purely from the name multiset, so they share one
    change gate. Skipped when the multiset is unchanged since the last publish:
    the roster notification also fires on activity heartbeats (~every 30s per
    participant), where names never change — re-broadcasting would fan out
    O(participants²) redundant messages and rewrite attendees.md for nothing.
    Clients only count occurrences of their own name, so the comparison is
    order-insensitive (sorted).
    """
    ps = participant_state
    names = _participant_display_names()
    names_key = sorted(names)
    if names_key == ps.last_broadcast_names:
        return
    ps.last_broadcast_names = names_key
    broadcast(ParticipantNamesUpdatedMsg(names=names))
    _regenerate_attendees()


async def _notify_host_participant_list():
    """Push the roster to the host, and the UUID-free names to all participants.

    The host payload keeps UUIDs (host is trusted) and goes out on every roster
    change (join / rename / activity / avatar / location). The participant
    names broadcast + attendees.md regen ride the same hook but only fire when
    the set of names actually changed (join / rename), not on heartbeats.
    """
    await notify_host(
        ParticipantListUpdatedMsg(
            participants=_build_host_participants_list(),
        )
    )
    _publish_names_if_changed()


async def _publish_scores_after_purge() -> None:
    """Re-publish the scoreboard after a participant was removed from it.

    The roster push alone would leave the leaderboard showing the deleted
    participant until the next scoring event. Participants get the UUID-free
    token-keyed map; the trusted host keeps the UUID-keyed one.
    """
    from daemon.scores import notify_host_scores, scores

    broadcast(ScoresUpdatedMsg(scores=scores.snapshot_tokenized()))
    await notify_host_scores()


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
        participants={
            uid: None for uid in ps.participant_names
        },  # fake WS entries for name pool checks
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
        # …unless they claimed trainer over loopback after registering. The claim
        # and this call race (different transports), so honour a late claim here
        # instead of echoing the pre-claim name back forever.
        if pid in ps.trainer_pids and ps.participant_names[pid] != RESERVED_TRAINER_NAME:
            ps.participant_names[pid] = RESERVED_TRAINER_NAME
            ps.anonymous_pids.discard(pid)
        return RegisterResponse(
            name=ps.participant_names[pid],
            avatar=ps.participant_avatars.get(pid, ""),
        )

    # New participant — assign identity
    raw_name: str
    # Sanitize at ingest: strip control/bidi/ANSI, collapse whitespace, NFC,
    # cap length. An all-noise name sanitizes to "" and falls through to the
    # auto-assign (anonymous) path just like an empty body.
    explicit_name = sanitize_name(body.name)
    name_conflict = False

    if pid in ps.trainer_pids:
        # Claimed trainer: the identity is fixed, never typed and never
        # auto-assigned. Overrides whatever name was sent.
        ps.anonymous_pids.discard(pid)
        explicit_name = RESERVED_TRAINER_NAME
    elif is_reserved_trainer_name(explicit_name):
        return JSONResponse({"error": "Name is reserved"}, status_code=403)

    if explicit_name:
        # Explicit typed name → NOT anonymous (even if it matches a fictional
        # pool entry). The anonymous tag is driven by an explicit signal, not by
        # guessing from pool membership.
        ps.anonymous_pids.discard(pid)
        # Uniqueness is checked but NEVER blocks: a taken name is accepted and
        # a soft conflict flag is returned (no 409). The in-session duplicate
        # indicator (driven by the names broadcast) handles it on the client.
        name_conflict = _is_name_taken(pid, explicit_name)
        raw_name = explicit_name
    elif ps.mode == "talk":
        # Conference mode: auto-assign character name → anonymous (no typed name).
        ps.anonymous_pids.add(pid)
        fake_state = _build_mini_state()
        char_name, universe = assign_conference_name(fake_state)
        raw_name = char_name
        ps.participant_universes[pid] = universe
    else:
        # Workshop mode: random LOTR name → anonymous (no typed name).
        ps.anonymous_pids.add(pid)
        # random LOTR name while trying to keep name/avatar in sync
        taken_names = set(ps.participant_names.values())
        taken_avatars = {
            a
            for uid, a in ps.participant_avatars.items()
            if uid != pid and not uid.startswith("__")
        }
        sync_candidates = [
            name
            for name in LOTR_NAMES
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
        taken_by_others = {
            a
            for uid, a in ps.participant_avatars.items()
            if uid != pid and not uid.startswith("__")
        }
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

    return RegisterResponse(name=raw_name, avatar=avatar, name_conflict=name_conflict)


@router.put("/name", response_model=RenameResponse)
async def rename_participant(request: Request, body: RenameRequest):
    """Rename a registered participant. Returns 400 if not yet registered.

    A duplicate name is accepted (never a 409): the response carries a soft
    `name_conflict` flag and the participant stays admitted.
    """
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    ps = participant_state

    if pid not in ps.participant_names:
        return JSONResponse(
            {"error": "Participant not registered — call /register first"}, status_code=400
        )

    # Sanitize at ingest (same choke point as register): strip control/bidi/ANSI,
    # collapse whitespace, NFC, cap length. A name that is empty after
    # sanitization (or all-noise) is rejected.
    raw_name = sanitize_name(body.name)
    if not raw_name:
        return JSONResponse({"error": "Name required"}, status_code=400)

    # Same gate as /register: the trainer name is a privilege, not a string.
    if is_reserved_trainer_name(raw_name) and pid not in ps.trainer_pids:
        return JSONResponse({"error": "Name is reserved"}, status_code=403)

    # A rename is always an explicitly typed name → NOT anonymous.
    ps.anonymous_pids.discard(pid)

    # Uniqueness is checked but NEVER blocks — accept the rename, flag the collision.
    name_conflict = _is_name_taken(pid, raw_name)

    ps.participant_names[pid] = raw_name

    await _notify_host_participant_list()

    return RenameResponse(name_conflict=name_conflict)


@router.post("/activity", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def report_activity(request: Request, body: ActivityReportRequest):
    """Merge a participant's per-view engagement deltas (active seconds/visits/clicks).

    Called by the participant page at most every ~30s while active, and on
    tab-hide/unload. Idle/backgrounded tabs send nothing.
    """
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    ps = participant_state
    bucket = ps.engagement.setdefault(pid, {})
    for view, delta in body.deltas.items():
        if view not in _KNOWN_VIEWS:
            continue
        cur = bucket.setdefault(view, {"seconds": 0, "visits": 0, "clicks": 0})
        cur["seconds"] += delta.seconds
        cur["visits"] += delta.visits
        cur["clicks"] += delta.clicks

    ps.last_active_at[pid] = time.time() * 1000.0  # epoch ms; host compares to Date.now()
    if body.current_view:
        ps.last_view[pid] = body.current_view

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

    quiz_data = _build_quiz_for_participant(pid)
    poll_fields = _build_poll_for_participant(pid)
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
        # Opaque token that keys this participant in the scores_updated broadcast.
        "my_score_token": _score_token(pid),
        "my_name": ps.participant_names.get(pid, ""),
        "my_avatar": ps.participant_avatars.get(pid, ""),
        "current_activity": ps.current_activity,
        "session_name": get_active_session_name(),
        # Roster display names only (UUID-free) — feeds the duplicate indicator.
        "participant_names": _participant_display_names(),
        # Wordcloud
        "wordcloud": {
            "words": wc.words,
            "word_order": wc.word_order,
            "topic": wc.topic,
        },
        # QA (personalised)
        "qa_questions": _build_qa_for_participant(pid),
        # Quiz (personalised)
        **quiz_data,
        # Poll (personalised)
        **poll_fields,
        # Codereview (personalised)
        "codereview": cr,
        # Debate (personalised, grouped, UUID-free)
        "debate": debate,
        # Emoji counters (talk mode)
        "emoji_counters": dict(ps.emoji_counters),
        # Slides (from misc state — synced from Railway)
        "slides_current": misc_state.current_slide,
        "talk_presentation_slug": misc_state.talk_presentation_slug,
        # Summary / notes (timestamps only — full content fetched on demand)
        "notes_updated_at": notes_updated_at,
        "summary_updated_at": summary["updated_at"],
        "slides_history_count": len(misc_state.slides_viewed),
        # Files opened this session (count only — full list fetched on demand)
        "files_count": _files_count(),
        # Agent prompts intercepted this session (count only — texts fetched on demand)
        "prompts_count": _prompts_count(),
        # Google Drive folder link for session materials
        "gdrive_url": session_shared_state.get_gdrive_url(),
        # End-of-session participant feedback form (freeonlinesurveys)
        "feedback_url": session_shared_state.get_feedback_url(),
        # Agenda .docx availability
        "has_agenda": misc_state.agenda_docx_path is not None
        and misc_state.agenda_docx_path.exists(),
        # Emoji reaction catalog — single source of truth; the page renders its
        # bar from this so the buttons and the daemon whitelist cannot drift.
        "emoji_catalog": [e.model_dump() for e in EMOJI_CATALOG],
        # Attention master switch — a fresh load / reconnect renders the bell +
        # permission affordance only when the host has enabled the capability.
        "attention_enabled": ps.attention_enabled,
    }

    return JSONResponse(state_msg)


def _get_current_session_id() -> str | None:
    """Safely get the current session ID from session_state module."""
    try:
        from daemon.session_state import get_current_session_id

        return get_current_session_id()
    except Exception:
        return None


# ── Host-only router ──

host_router = APIRouter(prefix="/api/{session_id}/host", tags=["participant"])


# Clears strays out of a live session — a test join, a second tab that took its
# own name, someone who left before the workshop started — without the
# stop-the-daemon-and-hand-edit-`session-state.json` dance that was the only way
# before. `daemon/participant/purge.py` owns the list of stores it clears; the
# three guards below are what keep a destructive endpoint boring:
#   * the proxy marker check keeps it on the trainer's machine. The host UI talks
#     to this daemon over loopback, so nothing legitimate arrives through Railway,
#     and this must never be one routing mistake away from the room.
#   * an unknown id is a 404, not a silent success — you asked to delete
#     something that is not there, and that usually means a mistyped uuid.
#   * an active participant is a 409, because deleting someone mid-session yanks
#     their identity out from under an open tab. `?force=true` says you mean it.
@host_router.delete("/participants/{participant_id}", response_model=PurgeReport)
async def delete_participant(
    request: Request, session_id: str, participant_id: str, force: bool = False
):
    """Delete an inactive participant and everything they left behind."""
    from daemon.participant.purge import is_active, is_known, purge_participant
    from daemon.proxy_handler import RAILWAY_PROXY_MARKER

    if request.headers.get(RAILWAY_PROXY_MARKER):
        return JSONResponse({"error": "Not available through the proxy"}, status_code=403)
    if not is_known(participant_id):
        return JSONResponse({"error": "Unknown participant"}, status_code=404)
    if is_active(participant_id) and not force:
        return JSONResponse(
            {
                "error": "Participant is still active — retry with ?force=true to delete anyway",
                "name": participant_state.participant_names.get(participant_id, ""),
            },
            status_code=409,
        )

    report = purge_participant(participant_id)
    from daemon import log as _log

    _log.info(
        "participant",
        f"🗑️  purged {report.name!r} ({participant_id[:8]}…) — {report.removed or 'nothing stored'}",
    )
    await _notify_host_participant_list()
    await _publish_scores_after_purge()
    return report


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
