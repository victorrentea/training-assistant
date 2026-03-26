"""Session stack management — host commands + daemon sync."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from auth import require_host_auth
from state import state
from messaging import broadcast_state
from daemon.transcript_query import load_normalized_entries

router = APIRouter()


def _get_sessions_root() -> Path | None:
    """Resolve the sessions root directory from env, same as quiz_core.find_session_folder."""
    sessions_root_str = os.environ.get(
        "SESSIONS_FOLDER",
        str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
    )
    p = Path(sessions_root_str).expanduser()
    return p if p.exists() and p.is_dir() else None


def _get_transcription_root() -> Path | None:
    folder_str = os.environ.get(
        "TRANSCRIPTION_FOLDER",
        "/Users/victorrentea/Documents/transcriptions",
    )
    p = Path(folder_str).expanduser()
    return p if p.exists() and p.is_dir() else None


def _normalize_transcript_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\t", " ")).strip()


class StartSessionRequest(BaseModel):
    name: str


class RenameSessionRequest(BaseModel):
    name: str


class SyncSessionRequest(BaseModel):
    main: dict | None = None
    talk: dict | None = None
    discussion_points: list = []
    session_state: dict | None = None
    action: str | None = None
    # backward compat:
    stack: list | None = None
    key_points: list | None = None


@router.post("/api/session/start", dependencies=[Depends(require_host_auth)])
async def start_session(body: StartSessionRequest):
    state.session_request = {"action": "start", "name": body.name}
    return {"ok": True}


@router.post("/api/session/end", dependencies=[Depends(require_host_auth)])
async def end_session():
    state.session_request = {"action": "end"}
    return {"ok": True}


@router.post("/api/session/pause", dependencies=[Depends(require_host_auth)])
async def pause_session():
    state.session_request = {"action": "pause"}
    if state.session_main:
        state.session_main = {**state.session_main, "status": "paused"}
        await broadcast_state()
    return {"ok": True}


@router.post("/api/session/resume", dependencies=[Depends(require_host_auth)])
async def resume_session():
    state.session_request = {"action": "resume"}
    if state.session_main:
        state.session_main = {**state.session_main, "status": "active"}
        await broadcast_state()
    return {"ok": True}


@router.post("/api/session/start_talk", dependencies=[Depends(require_host_auth)])
async def start_talk():
    state.session_request = {"action": "start_talk"}
    return {"ok": True}


@router.post("/api/session/end_talk", dependencies=[Depends(require_host_auth)])
async def end_talk():
    state.session_request = {"action": "end_talk"}
    return {"ok": True}


class SessionNameBody(BaseModel):
    name: str


@router.post("/api/session/create", dependencies=[Depends(require_host_auth)])
async def create_session(body: SessionNameBody):
    state.session_request = {"action": "create", "name": body.name}
    return {"ok": True}


@router.patch("/api/session/rename", dependencies=[Depends(require_host_auth)])
async def rename_session(body: RenameSessionRequest):
    state.session_request = {"action": "rename", "name": body.name}
    return {"ok": True}


@router.get("/api/session/request", dependencies=[Depends(require_host_auth)])
async def poll_session_request():
    req = state.session_request
    state.session_request = None
    if req:
        return req
    return {"action": None}


def _restore_state_from_snapshot(snap: dict):
    """Restores AppState from a session_state.json snapshot."""
    # Participants
    state.participant_history.clear()
    state.participant_names.clear()
    state.scores.clear()
    state.base_scores.clear()
    state.locations.clear()
    state.participant_avatars.clear()
    state.participant_universes.clear()
    for uuid, p in (snap.get("participants") or {}).items():
        state.participant_history.add(uuid)
        state.participant_names[uuid] = p["name"]
        state.scores[uuid] = p.get("score", 0)
        state.base_scores[uuid] = p.get("base_score", 0)
        state.locations[uuid] = p.get("location", "")
        state.participant_avatars[uuid] = p.get("avatar", "")
        state.participant_universes[uuid] = p.get("universe", "")

    # Mode
    if snap.get("mode"):
        state.mode = snap["mode"]

    # Activity
    if snap.get("activity"):
        from state import ActivityType
        try:
            state.current_activity = ActivityType(snap["activity"])
        except ValueError:
            pass

    # Poll
    state.poll = None
    state.poll_active = False
    state.votes = {}
    state.vote_times = {}
    state.poll_correct_ids = None
    state.poll_opened_at = None
    state.poll_timer_seconds = None
    state.poll_timer_started_at = None
    if snap.get("poll"):
        p = snap["poll"]
        exclude = {"active", "votes", "vote_times", "correct_ids", "opened_at", "timer_seconds", "timer_started_at"}
        state.poll = {k: v for k, v in p.items() if k not in exclude}
        state.poll_active = p.get("active", False)
        state.votes = p.get("votes") or {}
        state.vote_times = {uid: datetime.fromisoformat(t) for uid, t in (p.get("vote_times") or {}).items()}
        state.poll_correct_ids = p.get("correct_ids")
        state.poll_opened_at = datetime.fromisoformat(p["opened_at"]) if p.get("opened_at") else None
        state.poll_timer_seconds = p.get("timer_seconds")
        state.poll_timer_started_at = datetime.fromisoformat(p["timer_started_at"]) if p.get("timer_started_at") else None

    # QA
    state.qa_questions.clear()
    for q in (snap.get("qa") or {}).get("questions") or []:
        q_copy = dict(q)
        q_copy["upvoters"] = set(q_copy.get("upvoters") or [])
        state.qa_questions[q_copy["id"]] = q_copy

    # Wordcloud
    wc = snap.get("wordcloud") or {}
    state.wordcloud_topic = wc.get("topic", "")
    state.wordcloud_words = wc.get("words") or {}
    if hasattr(state, 'wordcloud_word_order'):
        state.wordcloud_word_order = wc.get("word_order") or []

    # Debate
    debate = snap.get("debate") or {}
    state.debate_statement = debate.get("statement")
    state.debate_phase = debate.get("phase")
    state.debate_sides = debate.get("sides") or {}
    state.debate_arguments = [{**a, "upvoters": set(a.get("upvoters") or [])} for a in (debate.get("arguments") or [])]
    state.debate_champions = debate.get("champions") or {}
    state.debate_auto_assigned = set(debate.get("auto_assigned") or [])
    state.debate_first_side = debate.get("first_side")
    state.debate_round_index = debate.get("round_index")
    state.debate_round_timer_seconds = debate.get("round_timer_seconds")
    state.debate_round_timer_started_at = None  # reset first
    if debate.get("round_timer_started_at"):
        state.debate_round_timer_started_at = datetime.fromisoformat(debate["round_timer_started_at"])

    # Codereview
    cr = snap.get("codereview") or {}
    state.codereview_snippet = cr.get("snippet")
    state.codereview_language = cr.get("language")
    state.codereview_phase = cr.get("phase", "idle")
    state.codereview_confirmed = set(cr.get("confirmed") or [])
    state.codereview_selections = {uid: set(lines) for uid, lines in (cr.get("selections") or {}).items()}

    # Misc
    state.leaderboard_active = snap.get("leaderboard_active", False)
    if snap.get("token_usage"):
        state.token_usage.update(snap["token_usage"])


@router.post("/api/session/sync", dependencies=[Depends(require_host_auth)])
async def sync_session(body: SyncSessionRequest):
    if body.main is not None or body.talk is not None:
        state.session_main = body.main
        state.session_talk = body.talk
    key_points = body.key_points or body.discussion_points
    if key_points:
        state.summary_points = key_points
        state.summary_updated_at = datetime.now()

    # Manage paused participants BEFORE restoring
    if body.action == "start_talk":
        state.paused_participant_uuids = set(state.participant_names.keys())
    elif body.action == "end_talk":
        state.paused_participant_uuids = set(state.participant_names.keys())

    if body.session_state:
        _restore_state_from_snapshot(body.session_state)

    # Plain server-restart restore: clear paused set
    if body.action is None and body.session_state:
        state.paused_participant_uuids = set()

    await broadcast_state()
    return {"ok": True}


class TimingEventBody(BaseModel):
    event: str
    minutes_remaining: int | None = None


@router.post("/api/session/timing_event", dependencies=[Depends(require_host_auth)])
async def timing_event(body: TimingEventBody):
    """Daemon notifies server of a time-based event; server pushes to host WS."""
    host_ws = state.participants.get("__host__")
    if host_ws:
        try:
            await host_ws.send_json({
                "type": "timing_event",
                "event": body.event,
                "minutes_remaining": body.minutes_remaining,
            })
        except Exception:
            pass
    return {"ok": True}


@router.get(
    "/api/session/interval-lines.txt",
    dependencies=[Depends(require_host_auth)],
    response_class=PlainTextResponse,
)
async def get_interval_lines_txt(
    start: str = Query(..., description="Interval start in ISO format"),
    end: str = Query(..., description="Interval end in ISO format"),
):
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid start/end datetime format") from exc

    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="End must be after start")

    root = _get_transcription_root()
    if root is None:
        raise HTTPException(status_code=404, detail="Transcription folder not found")

    lines: list[str] = []
    for dt, txt in load_normalized_entries(root, since_date=start_dt.date()):
        if dt < start_dt or dt >= end_dt:
            continue
        normalized = _normalize_transcript_text(txt)
        if not normalized:
            continue
        lines.append(f"[{dt.strftime('%Y-%m-%d %H:%M:%S')}] {normalized}")

    if not lines:
        normalized_files = list(root.glob("* transcription.txt"))
        if not normalized_files:
            raise HTTPException(status_code=404, detail="No normalized transcript files found")

    payload = "\n".join(lines) + ("\n" if lines else "")
    filename = (
        "session-interval-"
        + start_dt.strftime("%Y%m%d-%H%M")
        + "-"
        + end_dt.strftime("%Y%m%d-%H%M")
        + ".txt"
    )
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return PlainTextResponse(content=payload, headers=headers)


@router.get("/api/session/folders", dependencies=[Depends(require_host_auth)])
async def list_session_folders():
    root = _get_sessions_root()
    folders = []
    if root:
        folders = sorted([f.name for f in root.iterdir() if f.is_dir()], reverse=True)
    return {"folders": folders}


@router.get("/api/session/snapshot", dependencies=[Depends(require_host_auth)])
async def get_session_snapshot():
    """Returns full serializable session state for daemon to persist to disk every 5s."""
    participants = {}
    for uuid, name in state.participant_names.items():
        participants[uuid] = {
            "name": name,
            "score": state.scores.get(uuid, 0),
            "base_score": state.base_scores.get(uuid, 0),
            "location": state.locations.get(uuid, ""),
            "avatar": state.participant_avatars.get(uuid, ""),
            "universe": state.participant_universes.get(uuid, ""),
        }

    poll_data = None
    if state.poll:
        poll_data = {
            **state.poll,
            "active": state.poll_active,
            "votes": state.votes,
            "vote_times": {uid: t.isoformat() for uid, t in state.vote_times.items()},
            "correct_ids": state.poll_correct_ids or [],
            "opened_at": state.poll_opened_at.isoformat() if state.poll_opened_at else None,
            "timer_seconds": state.poll_timer_seconds,
            "timer_started_at": state.poll_timer_started_at.isoformat() if state.poll_timer_started_at else None,
        }

    qa_questions = []
    for q in state.qa_questions.values():
        qa_questions.append({**q, "upvoters": list(q.get("upvoters", set()))})

    debate_data = {
        "statement": state.debate_statement,
        "phase": state.debate_phase,
        "sides": state.debate_sides,
        "arguments": [{**a, "upvoters": list(a.get("upvoters", set()))} for a in state.debate_arguments],
        "champions": state.debate_champions,
        "auto_assigned": list(state.debate_auto_assigned),
        "first_side": state.debate_first_side,
        "round_index": state.debate_round_index,
        "round_timer_seconds": state.debate_round_timer_seconds,
        "round_timer_started_at": state.debate_round_timer_started_at.isoformat() if state.debate_round_timer_started_at else None,
    }

    codereview_data = {
        "snippet": state.codereview_snippet,
        "language": state.codereview_language,
        "phase": state.codereview_phase,
        "confirmed": list(state.codereview_confirmed),
        "selections": {uid: list(lines) for uid, lines in state.codereview_selections.items()},
    }

    return {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "mode": state.mode,
        "participants": participants,
        "activity": state.current_activity.value if state.current_activity else "none",
        "poll": poll_data,
        "qa": {"questions": qa_questions},
        "wordcloud": {
            "topic": state.wordcloud_topic,
            "words": state.wordcloud_words,
            "word_order": getattr(state, 'wordcloud_word_order', []),
        },
        "debate": debate_data,
        "codereview": codereview_data,
        "leaderboard_active": state.leaderboard_active,
        "token_usage": state.token_usage,
    }
