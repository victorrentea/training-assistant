import base64
import binascii
import hashlib as _hashlib_mod
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.messaging import (
    broadcast,
    broadcast_participant_update,
)
from core.metrics import (
    ws_connections_active,
    ws_messages_total,
)
from core.state import state, ActivityType
from features.ws.daemon_protocol import (
    MSG_SLIDES_CATALOG, MSG_SLIDE_INVALIDATED, MSG_DAEMON_PING,
    MSG_QUIZ_PREVIEW, MSG_QUIZ_STATUS,
    MSG_SESSION_SYNC, MSG_TRANSCRIPT_STATUS,
    MSG_TOKEN_USAGE, MSG_SLIDES_CURRENT, MSG_SLIDES_CLEAR,
    MSG_TRANSCRIPTION_LANGUAGE_STATUS, MSG_TIMING_EVENT, MSG_STATE_RESTORE,
    MSG_ACTIVITY_LOG, MSG_SESSION_FOLDERS,
    MSG_GLOBAL_STATE_SAVED, MSG_RELOAD,
    MSG_PROXY_RESPONSE,
    MSG_PARTICIPANT_REGISTERED, MSG_PARTICIPANT_LOCATION, MSG_PARTICIPANT_AVATAR_UPDATED,
    MSG_BROADCAST,
)
from features.ws.proxy_bridge import handle_proxy_response

router = APIRouter()
session_router = APIRouter()
logger = logging.getLogger(__name__)


async def _kick_old_connection(pid: str):
    if pid in state.participants:
        old_ws = state.participants[pid]
        try:
            await old_ws.send_text(json.dumps({"type": "kicked"}))
            await old_ws.close(code=1001)
        except Exception:
            pass
        del state.participants[pid]


def _is_host_authorized_for_ws(websocket: WebSocket) -> bool:
    raw = websocket.headers.get("authorization", "").strip()
    if not raw.lower().startswith("basic "):
        return False
    token = raw[6:].strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    if ":" not in decoded:
        return False
    username, password = decoded.split(":", 1)
    expected_user = os.environ.get("HOST_USERNAME") or "host"
    expected_pass = os.environ.get("HOST_PASSWORD") or "host"
    return (
        secrets.compare_digest(username.encode(), expected_user.encode())
        and secrets.compare_digest(password.encode(), expected_pass.encode())
    )


async def _handle_daemon_slides_catalog(data):
    from features.slides.cache import handle_slides_catalog
    await handle_slides_catalog(data.get("entries", []))

async def _handle_daemon_slide_invalidated(data):
    from features.slides.cache import handle_slide_invalidated
    slug = data.get("slug", "").strip()
    if slug:
        await handle_slide_invalidated(slug)


async def _handle_quiz_preview(data):
    """Daemon sends generated quiz preview."""
    quiz = data.get("quiz")
    if quiz is None:
        state.quiz_preview = None
    else:
        state.quiz_preview = {
            "question": quiz.get("question", ""),
            "options": quiz.get("options", []),
            "multi": quiz.get("multi", False),
            "correct_indices": quiz.get("correct_indices", []),
            "source": quiz.get("source"),
            "page": quiz.get("page"),
        }
    await broadcast({"type": "quiz_preview", "quiz": state.quiz_preview})


async def _handle_quiz_status(data):
    """Daemon sends quiz status update."""
    state.quiz_status = {"status": data.get("status", ""), "message": data.get("message", "")}
    if data.get("session_folder") is not None or data.get("session_notes") is not None:
        state.daemon_session_folder = data.get("session_folder")
        state.daemon_session_notes = data.get("session_notes")
    slides = data.get("slides")
    if slides is not None:
        import re
        _slug_re = re.compile(r"[^a-z0-9]+")
        def _slugify_inline(value: str) -> str:
            raw = value.strip().lower()
            raw = _slug_re.sub("-", raw).strip("-")
            return raw or "slide"
        normalized: list[dict] = []
        seen: set[str] = set()
        for idx, slide in enumerate(slides):
            name = (slide.get("name") or "").strip()
            url = (slide.get("url") or "").strip()
            if not name or not url:
                continue
            slug = (slide.get("slug") or "").strip() or _slugify_inline(name)
            if slug in seen:
                slug = f"{slug}-{idx+1}"
            seen.add(slug)
            normalized.append({
                "name": name,
                "slug": slug,
                "url": url,
                "updated_at": slide.get("updated_at"),
                "etag": slide.get("etag"),
                "last_modified": slide.get("last_modified"),
                "sync_status": slide.get("sync_status"),
                "sync_message": slide.get("sync_message"),
            })
        state.slides = normalized
        from features.slides.cache import sync_slides_updated_at
        sync_slides_updated_at()
    await broadcast({"type": "quiz_status", **state.quiz_status})



async def _handle_session_sync(data):
    """Daemon sends session state — replicate POST /api/session/sync."""
    if "main" in data:
        from features.session.router import _apply_session_main
        _apply_session_main(data.get("main"))

    session_state = data.get("session_state")
    if session_state:
        from features.session.router import _restore_state_from_snapshot
        _restore_state_from_snapshot(session_state)
        state.needs_restore = False

    await broadcast_participant_update()


async def _handle_transcript_status(data):
    """Daemon sends transcript progress — replicate POST /api/transcript-status."""
    line_count = data.get("line_count", 0)
    if line_count > state.transcript_line_count:
        state.transcript_last_content_at = datetime.now(timezone.utc)
    state.transcript_line_count = line_count
    state.transcript_total_lines = data.get("total_lines", 0)
    state.transcript_latest_ts = data.get("latest_ts")
    # No broadcast needed — transcript status is host-only info, host fetches via REST


async def _handle_token_usage(data):
    """Daemon sends LLM cost tracking — replicate POST /api/token-usage."""
    usage = {k: v for k, v in data.items() if k != "type"}
    state.token_usage = usage
    # No broadcast needed — token usage is host-only info


async def _handle_slides_current(data):
    """Daemon sends current slide info — replicate POST /api/slides/current."""
    state.slides_current = {
        "url": data.get("url"),
        "slug": data.get("slug"),
        "source_file": data.get("source_file"),
        "presentation_name": data.get("presentation_name"),
        "current_page": data.get("current_page"),
        "converter": data.get("converter"),
        "updated_at": data.get("updated_at") or datetime.now(timezone.utc).isoformat(),
    }
    # Targeted broadcast only — full broadcast_state() is unnecessary here and adds
    # latency on every slide advance by sending large personalized payloads to all participants.
    await broadcast({"type": "slides_current", "slides_current": state.slides_current})


async def _handle_slides_clear(data):
    """Daemon clears current slide — replicate DELETE /api/slides/current."""
    state.slides_current = None
    await broadcast({"type": "slides_current", "slides_current": None})


async def _handle_transcription_language_status(data):
    """Daemon confirms language change — replicate POST /api/transcription-language/status."""
    lang = data.get("language", "")
    state.transcription_language = lang
    await broadcast({"type": "transcription_language", "language": lang})


async def _handle_timing_event(data):
    """Daemon sends timing event — replicate POST /api/session/timing_event."""
    host_ws = state.participants.get("__host__")
    if host_ws:
        try:
            await host_ws.send_json({
                "type": "timing_event",
                "event": data.get("event"),
                "minutes_remaining": data.get("minutes_remaining"),
            })
        except Exception:
            pass
    # Also forward to overlay if connected
    overlay_ws = state.participants.get("__overlay__")
    if overlay_ws:
        try:
            await overlay_ws.send_json({
                "type": "timing_event",
                "event": data.get("event"),
                "minutes_remaining": data.get("minutes_remaining"),
            })
        except Exception:
            pass


def _parse_iso_or_none(s):
    """Parse an ISO datetime string back to datetime, or return None."""
    return datetime.fromisoformat(s) if s else None


async def _handle_state_restore(data):
    """Daemon sends full state backup to restore — replicate POST /api/state-restore."""
    restore_data = data.get("state", data)

    if "participant_names" in restore_data:
        state.participant_names = restore_data["participant_names"]
    if "participant_avatars" in restore_data:
        state.participant_avatars = restore_data["participant_avatars"]
    if "participant_universes" in restore_data:
        state.participant_universes = restore_data["participant_universes"]
    if "locations" in restore_data:
        state.locations = restore_data["locations"]
    if "mode" in restore_data:
        state.mode = restore_data["mode"]
    if "current_activity" in restore_data:
        state.current_activity = ActivityType(restore_data["current_activity"])
    if "leaderboard_active" in restore_data:
        state.leaderboard_active = restore_data["leaderboard_active"]
    if "poll" in restore_data:
        state.poll = restore_data["poll"]
    if "poll_active" in restore_data:
        state.poll_active = restore_data["poll_active"]
    if "votes" in restore_data:
        state.votes = restore_data["votes"]
    if "poll_correct_ids" in restore_data:
        state.poll_correct_ids = restore_data["poll_correct_ids"]
    if "poll_opened_at" in restore_data:
        state.poll_opened_at = _parse_iso_or_none(restore_data["poll_opened_at"])
    if "poll_timer_seconds" in restore_data:
        state.poll_timer_seconds = restore_data["poll_timer_seconds"]
    if "poll_timer_started_at" in restore_data:
        state.poll_timer_started_at = _parse_iso_or_none(restore_data["poll_timer_started_at"])
    if "wordcloud_words" in restore_data:
        state.wordcloud_words = restore_data["wordcloud_words"]
    if "wordcloud_word_order" in restore_data:
        state.wordcloud_word_order = restore_data["wordcloud_word_order"]
    if "wordcloud_topic" in restore_data:
        state.wordcloud_topic = restore_data["wordcloud_topic"]
    if "qa_questions" in restore_data:
        qa_questions = {}
        for qid, q in restore_data["qa_questions"].items():
            qa_questions[qid] = {**q, "upvoters": set(q.get("upvoters", []))}
        state.qa_questions = qa_questions
    if "summary_points" in restore_data:
        state.summary_points = restore_data["summary_points"]
    if "slides_current" in restore_data:
        state.slides_current = restore_data["slides_current"]
    if restore_data.get("session_id"):
        state.session_id = restore_data["session_id"]
    if restore_data.get("session_name"):
        state.session_name = restore_data["session_name"]

    state.needs_restore = False
    await broadcast_participant_update()
    restored_count = len(state.participant_names)
    logger.info("State restored via WS with %d participants", restored_count)


_SYNC_EXCLUDED = {"version.js", "deploy-info.json", "work-hours.js"}

def _build_static_hashes() -> dict[str, str]:
    """Build {relative_path: md5_hex} for all files in static/ (recursive)."""
    static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    hashes = {}
    if static_dir.is_dir():
        for f in static_dir.rglob("*"):
            if f.is_file() and f.name not in _SYNC_EXCLUDED:
                rel = str(f.relative_to(static_dir))
                md5 = _hashlib_mod.md5(f.read_bytes()).hexdigest()
                hashes[rel] = md5
    return hashes



async def _handle_activity_log(data):
    """Daemon sends slides log and git repos activity tracking."""
    state.slides_log = data.get("slides_log") or []
    state.git_repos = data.get("git_repos") or []
    # No broadcast needed — activity log is host-only info


async def _handle_session_folders(data):
    """Daemon pushes list of session folders from local disk."""
    folders = data.get("folders")
    if isinstance(folders, list):
        names: list[str] = []
        ids: dict[str, str] = {}
        for item in folders:
            if isinstance(item, str):
                names.append(item)
                continue
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                names.append(name)
                sid = item.get("session_id")
                if isinstance(sid, str) and sid.strip():
                    ids[name] = sid.strip()
        state.session_folders = names
        state.session_folder_ids = ids


async def _handle_global_state_saved(data):
    """Daemon confirms a global-state file write for a request_id."""
    request_id = str(data.get("request_id") or "").strip()
    if request_id:
        state.daemon_global_state_acks[request_id] = data


async def _handle_reload(data):
    """Daemon requests all participant browsers to reload (static files updated)."""
    logger.info("Daemon triggered browser reload (static files updated)")
    await broadcast({"type": "reload"})


async def _handle_participant_registered(data: dict):
    """Daemon registered a participant — update state and broadcast."""
    pid = data.get("participant_id")
    if not pid:
        return
    state.participant_history.add(pid)
    if "name" in data:
        state.participant_names[pid] = data["name"]
    if "avatar" in data:
        state.participant_avatars[pid] = data["avatar"]
    if "universe" in data:
        state.participant_universes[pid] = data["universe"]
    if "score" in data:
        state.scores.setdefault(pid, data["score"])
        state.base_scores.setdefault(pid, 0)
    await broadcast_participant_update()


async def _handle_participant_location(data: dict):
    """Daemon set participant location."""
    pid = data.get("participant_id")
    loc = data.get("location")
    if pid and loc:
        state.locations[pid] = loc
        await broadcast_participant_update()


async def _handle_participant_avatar_updated(data: dict):
    """Daemon refreshed participant avatar."""
    pid = data.get("participant_id")
    avatar = data.get("avatar")
    if pid and avatar:
        state.participant_avatars[pid] = avatar
        await broadcast_participant_update()


async def _handle_broadcast(data: dict):
    """Fan out a daemon broadcast event to all connected participant WSs."""
    event = data.get("event")
    if not event:
        return
    # Update score mirror if this is a scores_updated broadcast
    if event.get("type") == "scores_updated" and "scores" in event:
        state.scores = {k: v for k, v in event["scores"].items()}
    # Fan out to all participants
    msg = json.dumps(event)
    for pid, ws in list(state.participants.items()):
        if pid.startswith("__"):  # skip __host__, __overlay__
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            pass


_DAEMON_MSG_HANDLERS = {
    MSG_SLIDES_CATALOG: _handle_daemon_slides_catalog,
    MSG_SLIDE_INVALIDATED: _handle_daemon_slide_invalidated,
    MSG_DAEMON_PING: None,  # heartbeat only — last_seen already updated
    MSG_QUIZ_PREVIEW: _handle_quiz_preview,
    MSG_QUIZ_STATUS: _handle_quiz_status,
    MSG_SESSION_SYNC: _handle_session_sync,
    MSG_TRANSCRIPT_STATUS: _handle_transcript_status,
    MSG_TOKEN_USAGE: _handle_token_usage,
    MSG_SLIDES_CURRENT: _handle_slides_current,
    MSG_SLIDES_CLEAR: _handle_slides_clear,
    MSG_TRANSCRIPTION_LANGUAGE_STATUS: _handle_transcription_language_status,
    MSG_TIMING_EVENT: _handle_timing_event,
    MSG_STATE_RESTORE: _handle_state_restore,
    MSG_ACTIVITY_LOG: _handle_activity_log,
    MSG_SESSION_FOLDERS: _handle_session_folders,
    MSG_GLOBAL_STATE_SAVED: _handle_global_state_saved,
    MSG_RELOAD: _handle_reload,
    MSG_PROXY_RESPONSE: handle_proxy_response,
    MSG_PARTICIPANT_REGISTERED: _handle_participant_registered,
    MSG_PARTICIPANT_LOCATION: _handle_participant_location,
    MSG_PARTICIPANT_AVATAR_UPDATED: _handle_participant_avatar_updated,
    MSG_BROADCAST: _handle_broadcast,
}


@router.websocket("/ws/daemon")
async def daemon_websocket_endpoint(websocket: WebSocket):
    if not _is_host_authorized_for_ws(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # Kick old daemon connection if present.
    old_ws = state.daemon_ws
    if old_ws is not None and old_ws is not websocket:
        try:
            await old_ws.send_json({"type": "kicked"})
            await old_ws.close(code=1001)
        except Exception:
            pass

    state.daemon_ws = websocket
    state.daemon_last_seen = datetime.now(timezone.utc)
    state.needs_restore = False
    logger.info("Daemon WS connected")
    await broadcast({"type": "slides_catalog_changed"})

    # Send static file inventory for daemon to diff and upload changes
    try:
        static_hashes = _build_static_hashes()
        await websocket.send_json({"type": "sync_files", "static_hashes": static_hashes, "pdf_slugs": {}})
    except Exception:
        logger.warning("Failed to send sync_files to daemon")

    # Re-deliver any pending session request that was not yet processed (e.g. sent before WS drop)
    if state.session_request:
        import uuid as _uuid
        request_id = _uuid.uuid4().hex
        try:
            await websocket.send_json({"type": "session_request", **state.session_request, "request_id": request_id})
            logger.info("Re-delivered pending session_request action=%s to reconnected daemon", state.session_request.get("action"))
        except Exception:
            pass

    try:
        while True:
            data = await websocket.receive_json()
            state.daemon_last_seen = datetime.now(timezone.utc)
            msg_type = data.get("type")
            handler = _DAEMON_MSG_HANDLERS.get(msg_type)
            if handler is not None:
                try:
                    await handler(data)
                except Exception:
                    logger.exception("Error handling daemon message type: %s", msg_type)
            elif msg_type not in _DAEMON_MSG_HANDLERS:
                logger.warning("Unknown daemon message type: %s", msg_type)
    except WebSocketDisconnect:
        pass
    finally:
        if state.daemon_ws is websocket:
            state.daemon_ws = None
        logger.info("Daemon WS disconnected")
        await broadcast({"type": "slides_catalog_changed"})


async def _send_initial_messages(websocket: WebSocket) -> None:
    """Send slides_cache_status as a separate initial message after state."""
    try:
        await websocket.send_text(json.dumps({"type": "slides_cache_status", "slides_cache_status": state.slides_cache_status}))
    except Exception:
        pass


async def _handle_participant_connection(websocket: WebSocket, pid: str, is_host: bool, is_overlay: bool):
    """Shared logic for participant/host/overlay WebSocket connections.

    Handles: paused check, accept, name registration, message loop, disconnect cleanup.
    Caller must have already validated auth and session_id as appropriate.
    """
    role = "host" if is_host else ("overlay" if is_overlay else "participant")

    # Overlay reconnect: kick old overlay connection
    if is_overlay:
        await _kick_old_connection("__overlay__")

    # Host reconnect: kick old host connection
    if is_host:
        await _kick_old_connection("__host__")

    await websocket.accept()

    state.participants[pid] = websocket
    if not is_host and not is_overlay:
        state.participant_history.add(pid)
        forwarded = websocket.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (websocket.client.host if websocket.client else "")
        state.participant_ips[pid] = ip
    ws_connections_active.labels(role=role).inc()

    if is_overlay:
        state.participant_names["__overlay__"] = "Overlay"
        logger.info(f"Overlay connected ({len(state.participants)} total)")
        await broadcast_participant_update()
    elif is_host:
        state.participant_names["__host__"] = "Host"
        logger.info(f"Host connected ({len(state.participants)} total)")
        await _send_initial_messages(websocket)
        await broadcast_participant_update()
    else:
        # Participant registered via daemon REST — send initial state and broadcast presence
        name = state.participant_names.get(pid, "")
        logger.info(f"WS connected: {pid} name={name!r} ({len(state.participants)} total)")
        await _send_initial_messages(websocket)
        await broadcast_participant_update()

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")
            if msg_type:
                ws_messages_total.labels(type=msg_type).inc()
            # All participant actions go through daemon REST — just keep the WS alive for broadcasts

    except WebSocketDisconnect:
        state.participants.pop(pid, None)
        state.locations.pop(pid, None)
        state.participant_ips.pop(pid, None)
        ws_connections_active.labels(role=role).dec()
        # Keep participant_names and scores (persist for session)
        logger.info(f"Disconnected: {pid} ({len(state.participants)} remaining)")
        await broadcast_participant_update()


@session_router.websocket("/ws/{session_id}/{participant_id}")
async def session_websocket_endpoint(websocket: WebSocket, session_id: str, participant_id: str):
    """WebSocket endpoint for participants, host (__host__), and overlay (__overlay__), requiring a valid session_id."""
    # Validate session_id — accept first so client gets a clean close code
    if not state.session_id or session_id.lower() != state.session_id.lower():
        is_host_attempt = participant_id.strip() == "__host__"
        if is_host_attempt and not state.needs_restore:
            await websocket.accept()
            if state.session_id:
                await websocket.send_text(json.dumps({"type": "redirect", "url": f"/host/{state.session_id}"}))
            else:
                await websocket.send_text(json.dumps({"type": "redirect", "url": "/host"}))
            await websocket.close(code=1000)
        else:
            await websocket.accept()
            if state.session_id:
                await websocket.send_text(json.dumps({"type": "redirect", "url": f"/{state.session_id}"}))
            await websocket.close(code=1008)
        return

    pid = participant_id.strip()
    is_host = (pid == "__host__")
    is_overlay = (pid == "__overlay__")

    if not is_host and not is_overlay and (not pid or pid.startswith("__")):
        await websocket.accept()
        await websocket.close(code=1008)
        return

    await _handle_participant_connection(websocket, pid, is_host=is_host, is_overlay=is_overlay)
