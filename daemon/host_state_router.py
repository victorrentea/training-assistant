"""Daemon host state router — full state for host page load and WS reconnect."""
import logging
import os
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.codereview.state import codereview_state
from daemon.debate.state import debate_state
from daemon.leaderboard.state import leaderboard_state
from daemon.misc.content_files import read_notes_updated_at, read_summary_payload
from daemon.misc.state import misc_state
from daemon.participant.state import GitRepoActivity, participant_state
from daemon.poll.state import poll_state
from daemon.qa.state import qa_state
from daemon.session import state as session_shared_state
from daemon.wordcloud.state import wordcloud_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/{session_id}/host", tags=["host-state"])


class PasteEntry(BaseModel):
    id: str
    text: str


class UploadedFileEntry(BaseModel):
    id: str
    filename: str
    size: int
    disk_path: str
    seen_by_host: bool


class HostParticipant(BaseModel):
    uuid: str
    name: str
    score: int
    location: str
    location_tz: str = ""
    location_country: str = ""
    avatar: str
    paste_texts: list[PasteEntry] = []
    received_files: list[UploadedFileEntry] = []


class HostQAQuestion(BaseModel):
    id: str
    text: str
    author: str
    author_uuid: str
    author_avatar: str
    upvote_count: int
    upvoters: list[str]
    answered: bool
    timestamp: float


class HostPollVote(BaseModel):
    option_indices: list[int]
    voted_at: str


class PollData(BaseModel):
    id: str
    question: str
    options: list[str]
    multi: bool
    correct_count: int | None = None
    source: str | None = None
    page: str | None = None
    timer_seconds: int | None = None
    timer_started_at: str | None = None
    correct_indices: list[int] | None = None


class HostCodeReviewState(BaseModel):
    snippet: str | None = None
    language: str | None = None
    phase: str | None = None
    confirmed_lines: list[int] = []
    selections: dict[str, list[int]] = {}
    line_percentages: dict[int, int] | None = None
    line_counts: dict[int, int] | None = None


class DebateArgumentHost(BaseModel):
    id: str
    author_uuid: str
    side: str
    text: str
    upvoters: list[str]
    ai_generated: bool
    merged_into: str | None = None


class SlidesLogEntry(BaseModel):
    file: str
    slide: int
    seconds_spent: float
    timestamp: str


class LeaderboardEntry(BaseModel):
    uuid: str
    name: str
    score: int


class LeaderboardData(BaseModel):
    entries: list[LeaderboardEntry]
    total_participants: int


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class SlidesCurrentPayload(BaseModel):
    slug: str | None = None
    page: int | None = None


class PollQueueQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]


class PollQueueStatus(BaseModel):
    pending: int
    current: PollQueueQuestion | None


class HostStateResponse(BaseModel):
    type: Literal["state"] = "state"
    mode: str
    current_activity: str
    participant_count: int
    participants: list[HostParticipant]
    daemon_connected: bool
    railway_connected: bool
    overlay_connected: bool
    gdrive_running: bool
    wordcloud_words: dict[str, int]
    wordcloud_word_order: list[str]
    wordcloud_topic: str
    qa_questions: list[HostQAQuestion]
    poll: PollData | None = None
    poll_active: bool
    vote_counts: list[int]
    votes: dict[str, HostPollVote]
    codereview: HostCodeReviewState
    debate_statement: str | None = None
    debate_phase: str | None = None
    debate_side_counts: dict[str, int]
    debate_sides: dict[str, str]
    debate_arguments: list[DebateArgumentHost]
    debate_champions: dict[str, str]
    debate_auto_assigned: list[str]
    debate_first_side: str | None = None
    debate_round_index: int | None = None
    debate_round_timer_seconds: int | None = None
    debate_round_timer_started_at: str | None = None
    talk_presentation_name: str | None = None
    talk_presentation_slug: str | None = None
    slides_current: SlidesCurrentPayload | None = None
    slides_log: list[SlidesLogEntry]
    slides_log_deep_count: int
    slides_log_topic: str | None = None
    git_repos: list[GitRepoActivity] = []
    git_repos_count: int = 0
    session_id: str | None = None
    join_base_url: str
    daemon_session_folder: str | None = None
    daemon_session_notes: str | None = None
    session_type: str = "workshop"
    leaderboard_data: LeaderboardData | None = None
    notes_updated_at: str | None = None
    summary_updated_at: str | None = None
    token_usage: TokenUsage
    transcript_line_count: int
    transcript_total_lines: int
    transcript_latest_ts: str | None = None
    poll_queue: PollQueueStatus | None = None


def _build_host_participants_list() -> list[dict]:
    """Build participant list for host — all named, including offline."""
    from daemon.scores import scores as daemon_scores
    ps = participant_state
    all_pids = sorted(
        ps.participant_names.keys(),
        key=lambda pid: (-daemon_scores.scores.get(pid, 0), ps.participant_names.get(pid, ""), pid),
    )
    result = []
    for pid in all_pids:
        if pid.startswith("__"):
            continue
        entry = {
            "uuid": pid,
            "name": ps.participant_names.get(pid, f"Guest {pid[:8]}"),
            "score": daemon_scores.scores.get(pid, 0),
            "location": ps.locations.get(pid, ""),
            "location_tz": ps.location_timezones.get(pid, ""),
            "location_country": ps.location_countries.get(pid, ""),
            "avatar": ps.participant_avatars.get(pid, ""),
            "online": pid in ps.online_participants,
        }
        # Include paste texts if present (from misc_state)
        paste_entries = misc_state.paste_texts.get(pid, [])
        if paste_entries:
            entry["paste_texts"] = paste_entries
        uploaded_entries = misc_state.visible_uploaded_files(pid)
        if uploaded_entries:
            entry["received_files"] = uploaded_entries
        result.append(entry)
    return result


def _build_qa_for_host() -> list[dict]:
    """Build QA question list for host (no personalisation — shows all info)."""
    ps = participant_state
    questions = []
    for qid, q in sorted(
        qa_state.questions.items(),
        key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
    ):
        questions.append({
            "id": qid,
            "text": q["text"],
            "author": ps.participant_names.get(q["author"], "Unknown"),
            "author_uuid": q["author"],
            "author_avatar": ps.participant_avatars.get(q["author"], ""),
            "upvote_count": len(q["upvoters"]),
            "upvoters": list(q["upvoters"]),
            "answered": q["answered"],
            "timestamp": q["timestamp"],
        })
    return questions


def _build_codereview_for_host() -> dict:
    """Build codereview state for host — includes all selections with counts."""
    cr = codereview_state
    result = {
        "snippet": cr.snippet,
        "language": cr.language,
        "phase": cr.phase,
        "confirmed_lines": sorted(cr.confirmed),
        "selections": {pid: sorted(lines) for pid, lines in cr.selections.items()},
    }
    if cr.phase in ("reviewing",) and cr.snippet:
        line_count = len(cr.snippet.splitlines())
        total_participants = max(1, len([
            p for p in cr.selections if not p.startswith("__")
        ]))
        line_percentages: dict[int, int] = {}
        line_counts: dict[int, int] = {}
        for line_idx in range(line_count):
            sel_count = sum(1 for sels in cr.selections.values() if line_idx in sels)
            line_counts[line_idx] = sel_count
            line_percentages[line_idx] = round(sel_count * 100 / total_participants)
        result["line_percentages"] = line_percentages
        result["line_counts"] = line_counts
    return result


def _build_debate_for_host() -> dict:
    """Build debate state for host — full snapshot with side counts."""
    snap = debate_state.snapshot()
    for_count = sum(1 for s in debate_state.sides.values() if s == "for")
    against_count = sum(1 for s in debate_state.sides.values() if s == "against")
    snap["debate_side_counts"] = {"for": for_count, "against": against_count}
    return snap


def _build_poll_for_host() -> dict:
    """Build full poll state for host — includes all votes."""
    ps = poll_state
    poll = dict(ps.poll) if ps.poll else None
    if poll is not None:
        poll["timer_seconds"] = ps.poll_timer_seconds
        poll["timer_started_at"] = (
            ps.poll_timer_started_at.isoformat() if ps.poll_timer_started_at else None
        )
        poll["correct_indices"] = ps.poll_correct_indices

    return {
        "poll": poll,
        "poll_active": ps.poll_active,
        "vote_counts": ps.vote_counts() if ps.poll else [],
        "votes": dict(ps.votes),
    }


def _get_current_session_id() -> str | None:
    return session_shared_state.get_active_session_id()


def _get_session_name() -> str | None:
    return session_shared_state.get_active_session_name()


def _get_session_notes_filename() -> str | None:
    from daemon.misc.content_files import get_active_session_folder
    from daemon.session_state import find_notes_in_folder
    folder = get_active_session_folder()
    if folder is None:
        return None
    notes = find_notes_in_folder(folder)
    return notes.name if notes else None


def _get_join_base_url() -> str:
    return os.environ.get("WORKSHOP_SERVER_URL", "http://localhost:8000").rstrip("/")


def _build_slides_log_fields() -> dict:
    """Compute slides_log, slides_log_deep_count, slides_log_topic from in-memory slides_viewed."""

    slides_log = [
        {"file": sv["file_name"], "slide": sv["page"], "seconds_spent": sv["seconds"]}
        for sv in misc_state.slides_viewed
    ]
    deep_count = len({(e["file"], e["slide"]) for e in slides_log})
    if misc_state.slides_current and misc_state.slides_current.get("slug"):
        topic = misc_state.slides_current["slug"]
    elif slides_log:
        topic = max(slides_log, key=lambda e: e["seconds_spent"])["file"]
    else:
        topic = None
    return {
        "slides_log": slides_log,
        "slides_log_deep_count": deep_count,
        "slides_log_topic": topic,
    }


def _build_poll_queue_status() -> dict:
    """Build poll queue status for host state — pending count and current question."""
    from daemon.quiz.queue import quiz_queue
    current = quiz_queue.current()
    return {
        "pending": quiz_queue.pending_count(),
        "current": current,
    }


@router.get("/state", response_model=HostStateResponse)
async def get_host_state(request: Request, session_id: str):
    """Return full state for host page load — replicates Railway build_for_host()."""
    ps = participant_state
    participant_count = len([p for p in ps.participant_names if not p.startswith("__")])

    wc = wordcloud_state
    poll_data = _build_poll_for_host()
    cr = _build_codereview_for_host()
    debate = _build_debate_for_host()
    summary = read_summary_payload()
    notes_updated_at = read_notes_updated_at()

    state_msg = {
        "type": "state",
        # Core
        "mode": ps.mode,
        "current_activity": ps.current_activity,
        "participant_count": participant_count,
        "participants": _build_host_participants_list(),
        "daemon_connected": True,
        "railway_connected": _get_railway_connected(),
        "overlay_connected": _get_overlay_connected(),
        "gdrive_running": _get_gdrive_running(),
        # Wordcloud
        "wordcloud_words": wc.words,
        "wordcloud_word_order": wc.word_order,
        "wordcloud_topic": wc.topic,
        # QA
        "qa_questions": _build_qa_for_host(),
        # Poll
        **poll_data,
        # Codereview
        "codereview": cr,
        # Debate (flattened)
        "debate_statement": debate.get("statement"),
        "debate_phase": debate.get("phase"),
        "debate_side_counts": debate.get("debate_side_counts"),
        "debate_sides": debate.get("sides", {}),
        "debate_arguments": debate.get("arguments", []),
        "debate_champions": debate.get("champions", {}),
        "debate_auto_assigned": debate.get("auto_assigned", []),
        "debate_first_side": debate.get("first_side"),
        "debate_round_index": debate.get("round_index"),
        "debate_round_timer_seconds": debate.get("round_timer_seconds"),
        "debate_round_timer_started_at": debate.get("round_timer_started_at"),
        # Slides + session info (from misc state)
        "talk_presentation_name": misc_state.talk_presentation_name,
        "talk_presentation_slug": misc_state.talk_presentation_slug,
        "slides_current": misc_state.slides_current,
        **_build_slides_log_fields(),
        "git_repos": [r.model_dump() for r in participant_state.git_repos],
        "git_repos_count": len(participant_state.git_repos),
        # Session tracking
        "session_id": _get_current_session_id(),
        "join_base_url": _get_join_base_url(),
        "daemon_session_folder": _get_session_name(),
        "daemon_session_notes": _get_session_notes_filename(),
        "session_type": participant_state.mode or "workshop",
        # Leaderboard
        "leaderboard_data": leaderboard_state.data,
        # Summary / notes (timestamps only — full content fetched on modal open)
        "notes_updated_at": notes_updated_at,
        "summary_updated_at": summary["updated_at"],
        # Token usage
        "token_usage": _get_token_usage(),
        # Transcript info
        "transcript_line_count": 0,
        "transcript_total_lines": 0,
        "transcript_latest_ts": None,
        # Poll queue
        "poll_queue": _build_poll_queue_status(),
    }

    return JSONResponse(state_msg)


def _get_gdrive_running() -> bool:
    try:
        from daemon.slides.drive_sync import _is_google_drive_running
        return _is_google_drive_running()
    except Exception:
        return False


def _get_railway_connected() -> bool:
    try:
        from daemon.session_state import _ws_client
        return bool(_ws_client and _ws_client.connected)
    except Exception:
        return False


def _get_overlay_connected() -> bool:
    try:
        from daemon import addon_bridge_client
        return addon_bridge_client.is_connected()
    except Exception:
        return False


def _get_token_usage() -> dict:
    """Get token usage from LLM adapter if available."""
    try:
        from daemon.llm.adapter import get_usage
        return get_usage().to_dict()
    except Exception:
        return {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
