"""Session stack management — host commands + daemon sync."""

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core.auth import require_host_auth, require_host_auth_or_cookie
from core.state import state, ActivityType
from core.messaging import broadcast, broadcast_participant_update
from features.ws.daemon_protocol import push_to_daemon
from daemon.transcript.query import load_normalized_entries

router = APIRouter()          # global session endpoints
session_router = APIRouter()  # session-scoped endpoints (mounted under /api/{session_id}/, host-auth)
public_router = APIRouter()   # session-scoped public endpoints (mounted under /{session_id}/api/)
_GLOBAL_STATE_ACK_TIMEOUT_SECONDS = 3.0


def _normalize_session_name(name: str) -> str:
    """Replace non-breaking spaces and other Unicode whitespace with regular spaces."""
    return name.replace('\xa0', ' ').strip()


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


def _read_session_id_from_snapshot(path: Path) -> str | None:
    """Reads session_id from a session_state.json file."""
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    sid = data.get("session_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return None


def _load_session_id_for_folder(folder_name: str) -> str | None:
    """Best-effort local lookup for folder -> session_id."""
    root = _get_sessions_root()
    if root is None:
        return None
    return _read_session_id_from_snapshot(root / folder_name / "session_state.json")


def _resolve_session_id_for_folder(folder_name: str) -> str:
    """Return stable session_id for a folder, assigning one if missing."""
    normalized_name = _normalize_session_name(folder_name)
    existing = state.session_folder_ids.get(normalized_name)
    if existing:
        return existing

    loaded = _load_session_id_for_folder(normalized_name)
    if loaded:
        state.session_folder_ids[normalized_name] = loaded
        return loaded

    new_id = state.generate_session_id()
    state.session_folder_ids[normalized_name] = new_id
    return new_id


def _normalize_transcript_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\t", " ")).strip()


def _dedupe_normalized_folder_names(folders: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in folders:
        name = _normalize_session_name(str(raw))
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _filter_folders_to_current_year(folders: list[str], current_year: int | None = None) -> list[str]:
    year = current_year or datetime.now(timezone.utc).year
    year_prefix = str(year)
    return [name for name in folders if re.match(rf"^{re.escape(year_prefix)}(?!\d)", name)]


def _is_open_session(main: dict | None) -> bool:
    if not isinstance(main, dict) or not main:
        return False
    status = str(main.get("status") or "").strip().lower()
    if status in {"ended", "stopped", "closed"}:
        return False
    ended_at = main.get("ended_at")
    if isinstance(ended_at, str) and ended_at.strip():
        return False
    return True


async def _push_session_request_sync(session_request: dict) -> None:
    """Push session request to daemon and wait for global-state persistence ack when daemon is connected."""
    request_id = uuid.uuid4().hex
    sent = await push_to_daemon({"type": "session_request", **session_request, "request_id": request_id})
    if not sent or state.daemon_ws is None:
        return
    deadline = time.monotonic() + _GLOBAL_STATE_ACK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        ack = state.daemon_global_state_acks.pop(request_id, None)
        if ack is not None:
            return
        await asyncio.sleep(0.05)


def _apply_session_main(main: dict | None) -> None:
    """Apply daemon-provided main session and keep session_id stable."""
    if not _is_open_session(main):
        # Daemon confirmed session ended — clear the pending end request
        if state.session_request and state.session_request.get("action") == "end":
            state.session_request = None
        state.session_main = None
        return
    # If end was requested but daemon hasn't confirmed yet, ignore re-activation syncs
    if state.session_request and state.session_request.get("action") == "end":
        return

    state.session_main = main
    name = _normalize_session_name(str(main.get("name") or state.session_name or ""))
    if name:
        state.session_name = name
        if not state.session_id:
            state.session_id = _resolve_session_id_for_folder(name)
        if state.session_id:
            state.session_folder_ids[name] = state.session_id
    elif not state.session_id:
        state.generate_session_id()


def _clear_activity_state():
    """Clear all activity state for a fresh session. Preserves daemon WS, slides catalog, and WS connections."""
    # Polls
    state.poll = None
    state.poll_active = False
    state.votes = {}
    state.vote_times = {}
    state.poll_correct_ids = None
    state.poll_opened_at = None
    state.poll_timer_seconds = None
    state.poll_timer_started_at = None
    state.quiz_preview = None
    state.quiz_request = None
    state.quiz_refine_request = None
    state.quiz_status = None
    state.quiz_md_content = ""
    # Q&A
    state.qa_questions.clear()
    # Word cloud
    state.wordcloud_words.clear()
    state.wordcloud_word_order.clear()
    state.wordcloud_topic = ""
    # Scores are owned by daemon — send reset signal; local mirror will be updated via scores_updated broadcast
    # (fire-and-forget; daemon_ws may not be connected yet during startup)
    # Scores and participants
    state.participant_names.clear()
    state.participant_history.clear()
    state.participant_avatars.clear()
    state.participant_universes.clear()
    state.locations.clear()
    state.participant_ips.clear()
    state.paste_texts.clear()
    state.paste_next_id = 0
    state.uploaded_files.clear()
    state.upload_next_id = 0
    # Leaderboard
    state.leaderboard_active = False
    # Activity
    state.current_activity = ActivityType.NONE
    # Summary
    state.summary_points.clear()
    state.summary_updated_at = None
    state.notes_content = None
    # Session metadata
    state.session_main = None
    state.session_request = None
    state.slides_current = None
    state.slides_log = []
    state.git_repos = []
    state.needs_restore = False
    # Disconnect existing participants (they belong to the old session)
    state.paused_participant_uuids = set(state.participants.keys()) - {"__host__", "__overlay__"}


class StartSessionRequest(BaseModel):
    name: str


class RenameSessionRequest(BaseModel):
    name: str


class SyncSessionRequest(BaseModel):
    main: dict | None = None
    discussion_points: list = []
    session_state: dict | None = None
    action: str | None = None
    # backward compat:
    stack: list | None = None
    key_points: list | None = None
    slides_log: list = []
    git_repos: list = []


@router.post("/api/session/start", dependencies=[Depends(require_host_auth)])
async def start_session(body: StartSessionRequest):
    session_id = state.generate_session_id()
    name = _normalize_session_name(body.name)
    state.session_name = name
    state.session_request = {"action": "start", "name": name, "session_id": session_id}
    await _push_session_request_sync(state.session_request)
    return {"ok": True}


@router.post("/api/session/end", dependencies=[Depends(require_host_auth)])
async def end_session():
    state.session_request = {"action": "end"}
    await _push_session_request_sync(state.session_request)
    # Immediately mark session as ended on the backend so the host UI responds promptly,
    # even if the daemon hasn't confirmed yet (daemon will send a sync to clear it fully).
    if state.session_main:
        state.session_main = {**state.session_main, "status": "ended"}
        await broadcast({"type": "session_updated", "session_main": state.session_main})
    return {"ok": True}


@router.post("/api/session/pause", dependencies=[Depends(require_host_auth)])
async def pause_session():
    state.session_request = {"action": "pause"}
    await _push_session_request_sync(state.session_request)
    if state.session_main:
        state.session_main = {**state.session_main, "status": "paused"}
        await broadcast({"type": "session_updated", "session_main": state.session_main})
    return {"ok": True}


@router.post("/api/session/resume", dependencies=[Depends(require_host_auth)])
async def resume_session():
    state.session_request = {"action": "resume"}
    await _push_session_request_sync(state.session_request)
    if state.session_main:
        state.session_main = {**state.session_main, "status": "active"}
        await broadcast({"type": "session_updated", "session_main": state.session_main})
    return {"ok": True}


class SessionCreateBody(BaseModel):
    name: str
    type: str = "workshop"


@router.post("/api/session/create", dependencies=[Depends(require_host_auth_or_cookie)])
async def create_session(body: SessionCreateBody):
    name = _normalize_session_name(body.name)
    session_id = _resolve_session_id_for_folder(name)

    # Tell daemon to save the old session's state to disk first,
    # then clear activity state for the fresh session
    state.session_request = {"action": "create", "name": name, "session_id": session_id}
    await _push_session_request_sync(state.session_request)

    # Daemon has acked (saved old state) — now safe to clear
    _clear_activity_state()

    # Tell daemon to reset scores for the new session
    if state.daemon_ws:
        await state.daemon_ws.send_json({"type": "scores_reset"})

    state.session_id = session_id
    state.session_name = name
    state.session_type = body.type
    state.mode = "conference" if body.type == "talk" else "workshop"
    await broadcast_participant_update()
    return {"ok": True, "session_id": state.session_id, "session_name": state.session_name}


@router.patch("/api/session/rename", dependencies=[Depends(require_host_auth)])
async def rename_session(body: RenameSessionRequest):
    state.session_request = {"action": "rename", "name": _normalize_session_name(body.name)}
    await _push_session_request_sync(state.session_request)
    return {"ok": True}


def _restore_state_from_snapshot(snap: dict):
    """Restores AppState from a session_state.json snapshot."""
    # Participants
    state.participant_history.clear()
    state.participant_names.clear()
    state.locations.clear()
    state.participant_avatars.clear()
    state.participant_universes.clear()
    for uuid, p in (snap.get("participants") or {}).items():
        state.participant_history.add(uuid)
        state.participant_names[uuid] = p["name"]
        # scores are owned by daemon — not restored here
        state.locations[uuid] = p.get("location", "")
        state.participant_avatars[uuid] = p.get("avatar", "")
        state.participant_universes[uuid] = p.get("universe", "")

    if snap.get("mode"):
        state.mode = snap["mode"]

    if snap.get("activity"):
        from core.state import ActivityType
        try:
            state.current_activity = ActivityType(snap["activity"])
        except ValueError:
            pass

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

    _restore_activity_blocks_from_snapshot(snap)

    # Session ID (generate if missing — e.g. old snapshot from before session security)
    state.session_id = snap.get("session_id") or state.generate_session_id()

    # Session name and type
    if snap.get("session_name") is not None:
        state.session_name = snap["session_name"]
    if snap.get("session_type") is not None:
        state.session_type = snap["session_type"]

    # Misc
    state.leaderboard_active = snap.get("leaderboard_active", False)
    if snap.get("token_usage"):
        state.token_usage.update(snap["token_usage"])
    if snap.get("slides_log") is not None:
        state.slides_log = snap["slides_log"]
    if snap.get("git_repos") is not None:
        state.git_repos = snap["git_repos"]


def _restore_activity_blocks_from_snapshot(snap: dict):
    state.qa_questions.clear()
    for q in (snap.get("qa") or {}).get("questions") or []:
        q_copy = dict(q)
        q_copy["upvoters"] = set(q_copy.get("upvoters") or [])
        state.qa_questions[q_copy["id"]] = q_copy

    wc = snap.get("wordcloud") or {}
    state.wordcloud_topic = wc.get("topic", "")
    state.wordcloud_words = wc.get("words") or {}
    if hasattr(state, "wordcloud_word_order"):
        state.wordcloud_word_order = wc.get("word_order") or []


@session_router.post("/session/sync", dependencies=[Depends(require_host_auth)])
async def sync_session(body: SyncSessionRequest):
    if "main" in body.model_fields_set:
        _apply_session_main(body.main)
    key_points = body.key_points or body.discussion_points
    if key_points:
        state.summary_points = key_points
        state.summary_updated_at = datetime.now()

    if body.slides_log:
        state.slides_log = body.slides_log
    if body.git_repos:
        state.git_repos = body.git_repos

    if body.session_state:
        _restore_state_from_snapshot(body.session_state)
        if state.session_name and state.session_id:
            state.session_folder_ids[state.session_name] = state.session_id

    # Safety net: ensure session_id exists whenever a daemon-open session is active
    if _is_open_session(state.session_main) and not state.session_id:
        name = _normalize_session_name(str((state.session_main or {}).get("name") or ""))
        state.session_id = _resolve_session_id_for_folder(name) if name else state.generate_session_id()

    await broadcast_participant_update()
    return {"ok": True}


class TimingEventBody(BaseModel):
    event: str
    minutes_remaining: int | None = None


@session_router.post("/session/timing_event", dependencies=[Depends(require_host_auth)])
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


@session_router.get(
    "/session/interval-lines.txt",
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


@router.get("/api/session/folders", dependencies=[Depends(require_host_auth_or_cookie)])
async def list_session_folders():
    # Prefer daemon-pushed list (works on Railway where local filesystem isn't accessible)
    if state.session_folders:
        deduped = _dedupe_normalized_folder_names(state.session_folders)
        filtered = _filter_folders_to_current_year(deduped)
        state.session_folders = filtered
        return {"folders": filtered}
    # Fallback: scan local filesystem (works when running locally)
    root = _get_sessions_root()
    folders = []
    if root:
        deduped = _dedupe_normalized_folder_names(
            sorted([f.name for f in root.iterdir() if f.is_dir()], reverse=True)
        )
        folders = _filter_folders_to_current_year(deduped)
    return {"folders": folders}


# ── Public summary/notes endpoints (session-scoped, no auth) ──

@public_router.get("/api/summary")
async def get_summary():
    return {
        "points": state.summary_points,
        "updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
    }


@public_router.get("/api/notes")
async def get_notes():
    return {
        "content": state.notes_content,
        "summary_points": state.summary_points,
        "raw_markdown": state.summary_raw_markdown,
        "summary_updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
    }


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

    return {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "session_id": state.session_id,
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
        "leaderboard_active": state.leaderboard_active,
        "token_usage": state.token_usage,
        "slides_log": state.slides_log,
        "git_repos": state.git_repos,
    }


@router.get("/api/session/active")
async def get_session_active():
    """Public endpoint: returns whether a session is active (no code revealed)."""
    main_open = _is_open_session(state.session_main)
    pending_create = (
        isinstance(state.session_request, dict)
        and state.session_request.get("action") == "create"
        and state.session_id is not None
    )
    if main_open and not state.session_id:
        folder_name = _normalize_session_name(str((state.session_main or {}).get("name") or state.session_name or ""))
        state.session_id = _resolve_session_id_for_folder(folder_name) if folder_name else state.generate_session_id()
    active = (main_open and state.session_id is not None) or pending_create
    auto_join = ((main_open and state.session_id is not None) or pending_create)
    name = state.session_name or ((state.session_main or {}).get("name") if isinstance(state.session_main, dict) else None)
    return {
        "active": active,
        "auto_join": auto_join,
        "session_id": state.session_id,
        "session_name": name,
    }


class ResumeFolderBody(BaseModel):
    folder_name: str


@router.post("/api/session/resume-folder", dependencies=[Depends(require_host_auth_or_cookie)])
async def resume_session_folder(body: ResumeFolderBody):
    """Host resumes a past session from a folder. Reuses old session_id from snapshot if available."""
    folder_name = _normalize_session_name(body.folder_name)
    state.session_name = folder_name
    state.session_id = _resolve_session_id_for_folder(folder_name)
    state.session_request = {"action": "create", "name": folder_name, "session_id": state.session_id}
    await _push_session_request_sync(state.session_request)
    return {"ok": True, "session_id": state.session_id, "session_name": state.session_name}
