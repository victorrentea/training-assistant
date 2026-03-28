import base64
import binascii
import json
import logging
import os
import secrets
import time
import uuid as uuid_mod
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.messaging import (
    broadcast,
    broadcast_state,
    broadcast_participant_update,
    build_participant_state,
    send_state_to_participant,
    send_state_to_host,
    send_emoji_to_overlay,
    send_emoji_to_host,
)
from core.metrics import (
    ws_connections_active,
    ws_messages_total,
    poll_votes_total,
    poll_vote_duration_seconds,
    qa_questions_total,
    qa_upvotes_total,
)
from core.state import state, ActivityType, assign_avatar, refresh_avatar
from core.messaging import participant_ids
from features.debate.router import auto_assign_remaining
from features.ws.daemon_protocol import (
    MSG_SLIDES_CATALOG, MSG_SLIDE_INVALIDATED, MSG_DAEMON_PING,
    MSG_QUIZ_PREVIEW, MSG_QUIZ_STATUS, MSG_POLL_CREATE, MSG_POLL_OPEN,
    MSG_DEBATE_AI_RESULT, MSG_SESSION_SYNC, MSG_TRANSCRIPT_STATUS,
    MSG_TOKEN_USAGE, MSG_NOTES_CONTENT, MSG_SLIDES_CURRENT, MSG_SLIDES_CLEAR,
    MSG_TRANSCRIPTION_LANGUAGE_STATUS, MSG_TIMING_EVENT, MSG_STATE_RESTORE,
    MSG_ACTIVITY_LOG,
)

router = APIRouter()
session_router = APIRouter()
logger = logging.getLogger(__name__)


async def _record_vote_and_broadcast(pid: str):
    if pid not in state.vote_times:
        state.vote_times[pid] = datetime.now(timezone.utc)
        poll_votes_total.inc()
        if state.poll_opened_at:
            duration = (datetime.now(timezone.utc) - state.poll_opened_at).total_seconds()
            poll_vote_duration_seconds.observe(duration)
    await broadcast({
        "type": "vote_update",
        "vote_counts": state.vote_counts(),
        "total_votes": len(state.votes),
    })


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


async def _handle_poll_create(data):
    """Daemon sends quiz as a poll — replicate POST /api/poll logic."""
    question = str(data.get("question", "")).strip()
    options = data.get("options", [])
    multi = data.get("multi", False)
    correct_count = data.get("correct_count")
    source = data.get("source")
    page = data.get("page")

    if not question or len(options) < 2:
        logger.warning("poll_create: invalid data (question=%r, options=%d)", question, len(options))
        return

    state.poll = {
        "id": int(datetime.now(timezone.utc).timestamp() * 1000),
        "question": question,
        "multi": multi,
        "correct_count": correct_count if multi else None,
        "options": [
            {"id": f"opt{i}", "text": str(opt).strip()}
            for i, opt in enumerate(options)
            if str(opt).strip()
        ],
        "source": source or None,
        "page": page or None,
    }
    state.current_activity = ActivityType.POLL
    state.poll_active = False
    state.votes = {}
    state.poll_correct_ids = None
    await broadcast_state()


async def _handle_poll_open(data):
    """Daemon opens the poll — replicate PUT /api/poll/status with open=true."""
    if not state.poll:
        logger.warning("poll_open: no poll created")
        return
    open_flag = data.get("open", True)
    state.poll_active = open_flag
    if open_flag:
        state.poll_opened_at = datetime.now(timezone.utc)
        state.vote_times = {}
        state.base_scores = dict(state.scores)
    else:
        state.poll_timer_seconds = None
        state.poll_timer_started_at = None
    await broadcast_state()


async def _handle_debate_ai_result(data):
    """Daemon sends AI cleanup results — replicate POST /api/debate/ai-result."""
    if state.debate_phase != "ai_cleanup":
        logger.warning("debate_ai_result: not in ai_cleanup phase (current: %s)", state.debate_phase)
        return

    merges = data.get("merges", [])
    cleaned = data.get("cleaned", [])
    new_arguments = data.get("new_arguments", [])

    for merge in merges:
        keep_id = merge.get("keep_id")
        for remove_id in merge.get("remove_ids", []):
            for arg in state.debate_arguments:
                if arg["id"] == remove_id:
                    arg["merged_into"] = keep_id
                    kept = next((a for a in state.debate_arguments if a["id"] == keep_id), None)
                    if kept:
                        kept["upvoters"] = kept["upvoters"] | arg["upvoters"]

    for c in cleaned:
        for arg in state.debate_arguments:
            if arg["id"] == c.get("id"):
                arg["text"] = c["text"]

    for new_arg in new_arguments:
        state.debate_arguments.append({
            "id": str(uuid_mod.uuid4()),
            "author_uuid": "__ai__",
            "side": new_arg["side"],
            "text": new_arg["text"],
            "upvoters": set(),
            "ai_generated": True,
            "merged_into": None,
        })

    logger.info("AI result via WS: %d merges, %d new args", len(merges), len(new_arguments))
    state.debate_phase = "prep"
    await broadcast_state()


async def _handle_session_sync(data):
    """Daemon sends session state — replicate POST /api/session/sync."""
    if data.get("main") is not None or data.get("talk") is not None:
        state.session_main = data.get("main")
        state.session_talk = data.get("talk")
    key_points = data.get("key_points") or data.get("discussion_points") or []
    if key_points:
        state.summary_points = key_points
        state.summary_updated_at = datetime.now(timezone.utc)

    action = data.get("action")
    if action == "start_talk":
        state.paused_participant_uuids = set(state.participant_names.keys())
    elif action == "end_talk":
        state.paused_participant_uuids = set(state.participant_names.keys())

    session_state = data.get("session_state")
    if session_state:
        from features.session.router import _restore_state_from_snapshot
        _restore_state_from_snapshot(session_state)

    if action is None and session_state:
        state.paused_participant_uuids = set()

    await broadcast_state()


async def _handle_transcript_status(data):
    """Daemon sends transcript progress — replicate POST /api/transcript-status."""
    line_count = data.get("line_count", 0)
    if line_count > state.transcript_line_count:
        state.transcript_last_content_at = datetime.now(timezone.utc)
    state.transcript_line_count = line_count
    state.transcript_total_lines = data.get("total_lines", 0)
    state.transcript_latest_ts = data.get("latest_ts")
    await broadcast_state()


async def _handle_token_usage(data):
    """Daemon sends LLM cost tracking — replicate POST /api/token-usage."""
    usage = {k: v for k, v in data.items() if k != "type"}
    state.token_usage = usage
    await broadcast_state()


async def _handle_notes_content(data):
    """Daemon sends notes text — replicate POST /api/notes."""
    state.notes_content = data.get("content")
    await broadcast_state()


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
    await broadcast_state()
    await broadcast({"type": "slides_current", "slides_current": state.slides_current})


async def _handle_slides_clear(data):
    """Daemon clears current slide — replicate DELETE /api/slides/current."""
    state.slides_current = None
    await broadcast_state()
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


async def _handle_state_restore(data):
    """Daemon sends full state backup to restore — replicate POST /api/state-restore."""
    from features.snapshot.router import _parse_iso_or_none
    restore_data = data.get("state", data)

    if "participant_names" in restore_data:
        state.participant_names = restore_data["participant_names"]
    if "participant_avatars" in restore_data:
        state.participant_avatars = restore_data["participant_avatars"]
    if "participant_universes" in restore_data:
        state.participant_universes = restore_data["participant_universes"]
    if "scores" in restore_data:
        state.scores = restore_data["scores"]
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
    if "codereview_snippet" in restore_data:
        state.codereview_snippet = restore_data["codereview_snippet"]
    if "codereview_language" in restore_data:
        state.codereview_language = restore_data["codereview_language"]
    if "codereview_phase" in restore_data:
        state.codereview_phase = restore_data["codereview_phase"]
    if "codereview_selections" in restore_data:
        state.codereview_selections = {
            uid: set(lines) for uid, lines in restore_data["codereview_selections"].items()
        }
    if "codereview_confirmed" in restore_data:
        state.codereview_confirmed = set(restore_data["codereview_confirmed"])
    if "debate_statement" in restore_data:
        state.debate_statement = restore_data["debate_statement"]
    if "debate_phase" in restore_data:
        state.debate_phase = restore_data["debate_phase"]
    if "debate_sides" in restore_data:
        state.debate_sides = restore_data["debate_sides"]
    if "debate_champions" in restore_data:
        state.debate_champions = restore_data["debate_champions"]
    if "debate_auto_assigned" in restore_data:
        state.debate_auto_assigned = set(restore_data["debate_auto_assigned"])
    if "debate_first_side" in restore_data:
        state.debate_first_side = restore_data["debate_first_side"]
    if "debate_round_index" in restore_data:
        state.debate_round_index = restore_data["debate_round_index"]
    if "debate_round_timer_seconds" in restore_data:
        state.debate_round_timer_seconds = restore_data["debate_round_timer_seconds"]
    if "debate_round_timer_started_at" in restore_data:
        state.debate_round_timer_started_at = _parse_iso_or_none(restore_data["debate_round_timer_started_at"])
    if "debate_arguments" in restore_data:
        state.debate_arguments = [
            {**arg, "upvoters": set(arg.get("upvoters", []))}
            for arg in restore_data["debate_arguments"]
        ]
    if "summary_points" in restore_data:
        state.summary_points = restore_data["summary_points"]
    if "slides_current" in restore_data:
        state.slides_current = restore_data["slides_current"]

    state.needs_restore = False
    await broadcast_state()
    restored_count = len(state.participant_names)
    logger.info("State restored via WS with %d participants", restored_count)


async def _build_state_snapshot() -> dict:
    """Build a state snapshot dict for pushing to daemon."""
    from features.snapshot.router import _serialize_state
    import hashlib as _hashlib
    state_dict = _serialize_state()
    state_json = json.dumps(state_dict, sort_keys=True)
    md5_hex = _hashlib.md5(state_json.encode()).hexdigest()
    return {"type": "state_snapshot_result", "hash": md5_hex, "state": state_dict}


async def _build_session_snapshot() -> dict:
    """Build a session snapshot dict for pushing to daemon."""
    from features.session.router import get_session_snapshot
    snapshot = await get_session_snapshot()
    return {"type": "session_snapshot_result", **snapshot}


async def snapshot_pusher():
    """Push state and session snapshots to daemon every 7 seconds."""
    import asyncio
    while True:
        await asyncio.sleep(7)
        if state.daemon_ws is None:
            continue
        try:
            msg = await _build_state_snapshot()
            await state.daemon_ws.send_json(msg)
        except Exception:
            pass
        try:
            msg = await _build_session_snapshot()
            await state.daemon_ws.send_json(msg)
        except Exception:
            pass


async def _handle_activity_log(data):
    """Daemon sends slides log and git repos activity tracking."""
    state.slides_log = data.get("slides_log") or []
    state.git_repos = data.get("git_repos") or []
    await broadcast_state()


_DAEMON_MSG_HANDLERS = {
    MSG_SLIDES_CATALOG: _handle_daemon_slides_catalog,
    MSG_SLIDE_INVALIDATED: _handle_daemon_slide_invalidated,
    MSG_DAEMON_PING: None,  # heartbeat only — last_seen already updated
    MSG_QUIZ_PREVIEW: _handle_quiz_preview,
    MSG_QUIZ_STATUS: _handle_quiz_status,
    MSG_POLL_CREATE: _handle_poll_create,
    MSG_POLL_OPEN: _handle_poll_open,
    MSG_DEBATE_AI_RESULT: _handle_debate_ai_result,
    MSG_SESSION_SYNC: _handle_session_sync,
    MSG_TRANSCRIPT_STATUS: _handle_transcript_status,
    MSG_TOKEN_USAGE: _handle_token_usage,
    MSG_NOTES_CONTENT: _handle_notes_content,
    MSG_SLIDES_CURRENT: _handle_slides_current,
    MSG_SLIDES_CLEAR: _handle_slides_clear,
    MSG_TRANSCRIPTION_LANGUAGE_STATUS: _handle_transcription_language_status,
    MSG_TIMING_EVENT: _handle_timing_event,
    MSG_STATE_RESTORE: _handle_state_restore,
    MSG_ACTIVITY_LOG: _handle_activity_log,
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
    logger.info("Daemon WS connected")
    await broadcast({"type": "slides_catalog_changed"})

    try:
        while True:
            data = await websocket.receive_json()
            state.daemon_last_seen = datetime.now(timezone.utc)
            msg_type = data.get("type")
            handler = _DAEMON_MSG_HANDLERS.get(msg_type)
            if handler is not None:
                await handler(data)
            elif msg_type not in _DAEMON_MSG_HANDLERS:
                logger.warning("Unknown daemon message type: %s", msg_type)
    except WebSocketDisconnect:
        pass
    finally:
        if state.daemon_ws is websocket:
            state.daemon_ws = None
        logger.info("Daemon WS disconnected")
        await broadcast({"type": "slides_catalog_changed"})


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

    # UUID resolution: check if this UUID belongs to the paused session
    if not is_host and not is_overlay and pid in state.paused_participant_uuids:
        await websocket.send_json({
            "type": "session_paused",
            "message": "Session paused — you'll reconnect automatically"
        })
        await websocket.close()
        return

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
        await send_state_to_host(websocket)
        await broadcast_participant_update()
    else:
        # Participant: wait for set_name before sending state
        logger.info(f"WS connected: {pid} (awaiting set_name)")

    named = is_host or is_overlay  # host and overlay are always "named"

    # In conference mode, auto-name and mark as named immediately
    if state.mode == "conference" and not named:
        state.participant_names[pid] = ""
        named = True
        await websocket.send_text(json.dumps(build_participant_state(pid)))

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")
            if msg_type:
                ws_messages_total.labels(type=msg_type).inc()

            # Before named, only accept set_name
            if not named:
                if msg_type != "set_name":
                    continue
                name = str(data.get("name", "")).strip()[:32]
                if not name:
                    continue
                state.participant_names[pid] = name
                if not is_host:
                    assign_avatar(state, pid, name)
                named = True
                logger.info(f"Named: {pid} -> {name} ({len(state.participants)} total)")
                # Auto-assign late joiner to debate if past side_selection
                if (not is_host
                    and state.debate_phase
                    and state.debate_phase != "side_selection"
                    and pid not in state.debate_sides):
                    for_count, against_count = state.debate_side_counts()
                    state.debate_sides[pid] = "for" if for_count <= against_count else "against"
                    state.debate_auto_assigned.add(pid)
                    logger.info(f"Late joiner {name} auto-assigned to {state.debate_sides[pid]}")
                await send_state_to_participant(websocket, pid)
                await broadcast_participant_update()
                if not is_host and state.debate_phase:
                    await broadcast_state()
                continue

            if msg_type == "set_name":
                # Allow rename
                name = str(data.get("name", "")).strip()[:32]
                if name:
                    state.participant_names[pid] = name
                    if not is_host:
                        assign_avatar(state, pid, name)  # no-op if already assigned
                    await broadcast_participant_update()

            elif msg_type == "refresh_avatar":
                if not is_host:
                    rejected = set(data.get("rejected", []))
                    new_avatar = refresh_avatar(state, pid, rejected)
                    if new_avatar:
                        await send_state_to_participant(websocket, pid)
                        await broadcast_participant_update()

            elif msg_type == "location":
                loc = str(data.get("location", "")).strip()[:80]
                if loc:
                    state.locations[pid] = loc
                    await broadcast_participant_update()

            elif msg_type == "vote":
                option_id = data.get("option_id")
                valid_ids = [o["id"] for o in state.poll["options"]] if state.poll else []
                if (
                    state.poll_active
                    and state.poll
                    and not state.poll.get("multi")
                    and option_id in valid_ids
                ):
                    state.votes[pid] = option_id
                    await _record_vote_and_broadcast(pid)

            elif msg_type == "multi_vote":
                option_ids = data.get("option_ids", [])
                valid_ids = [o["id"] for o in state.poll["options"]] if state.poll else []
                correct_count = state.poll.get("correct_count") if state.poll else None
                max_allowed = correct_count if correct_count else len(valid_ids)
                if (
                    state.poll_active
                    and state.poll
                    and state.poll.get("multi")
                    and isinstance(option_ids, list)
                    and len(option_ids) <= max_allowed
                    and len(set(option_ids)) == len(option_ids)
                    and all(oid in valid_ids for oid in option_ids)
                ):
                    state.votes[pid] = option_ids
                    await _record_vote_and_broadcast(pid)

            elif msg_type == "wordcloud_word":
                word = str(data.get("word", "")).strip().lower()
                if state.current_activity == ActivityType.WORDCLOUD and word:
                    if word not in state.wordcloud_words:
                        state.wordcloud_word_order.insert(0, word)
                    state.wordcloud_words[word] = state.wordcloud_words.get(word, 0) + 1
                    if not is_host:
                        state.add_score(pid, 200)
                    await broadcast_state()

            elif msg_type == "qa_submit":
                text = str(data.get("text", "")).strip()
                if text and len(text) <= 280:
                    qid = str(uuid_mod.uuid4())
                    state.qa_questions[qid] = {
                        "id": qid,
                        "text": text,
                        "author": pid,
                        "upvoters": set(),
                        "answered": False,
                        "timestamp": time.time(),
                    }
                    state.add_score(pid, 100)
                    qa_questions_total.inc()
                    await broadcast_state()

            elif msg_type == "qa_upvote":
                question_id = data.get("question_id")
                q = state.qa_questions.get(question_id)
                if q and q["author"] != pid and pid not in q["upvoters"]:
                    q["upvoters"].add(pid)
                    author_pid = q["author"]
                    state.add_score(author_pid, 50)
                    state.add_score(pid, 25)
                    qa_upvotes_total.inc()
                    await broadcast_state()

            elif msg_type == "debate_pick_side":
                side = data.get("side")
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase == "side_selection"
                    and side in ("for", "against")
                    and pid not in state.debate_sides
                    and not is_host
                ):
                    state.debate_sides[pid] = side

                    # Auto-assign remaining when at least half have picked
                    all_pids = [p for p in participant_ids() if p != "__host__"]
                    newly = auto_assign_remaining(all_pids, state.debate_sides)
                    if newly:
                        state.debate_auto_assigned.update(newly)
                        logger.info(f"Auto-assigned {len(newly)} participants (≥50% picked)")

                    # Auto-advance if all participants now have sides and both sides have members
                    if all(p in state.debate_sides for p in all_pids):
                        fc, ac = state.debate_side_counts()
                        if fc > 0 and ac > 0:
                            state.debate_phase = "arguments"
                            logger.info("All participants assigned — auto-advancing to arguments phase")

                    await broadcast_state()

            elif msg_type == "debate_argument":
                text = str(data.get("text", "")).strip()
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase == "arguments"
                    and text
                    and len(text) <= 280
                    and pid in state.debate_sides
                    and not is_host
                ):
                    arg_id = str(uuid_mod.uuid4())
                    state.debate_arguments.append({
                        "id": arg_id,
                        "author_uuid": pid,
                        "side": state.debate_sides[pid],
                        "text": text,
                        "upvoters": set(),
                        "ai_generated": False,
                        "merged_into": None,
                    })
                    state.add_score(pid, 100)
                    await broadcast_state()

            elif msg_type == "debate_upvote":
                arg_id = data.get("argument_id")
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase in ("arguments", "ai_cleanup", "prep")
                    and not is_host
                ):
                    arg = next((a for a in state.debate_arguments if a["id"] == arg_id), None)
                    if arg and pid not in arg["upvoters"] and arg["author_uuid"] != pid:
                        arg["upvoters"].add(pid)
                        if arg["author_uuid"] != "__ai__":
                            state.add_score(arg["author_uuid"], 50)
                        state.add_score(pid, 25)
                        await broadcast_state()

            elif msg_type == "debate_volunteer":
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase == "prep"
                    and pid in state.debate_sides
                    and not is_host
                ):
                    my_side = state.debate_sides[pid]
                    if my_side not in state.debate_champions:
                        state.debate_champions[my_side] = pid
                        state.add_score(pid, 2500)
                        await broadcast_state()

            elif msg_type == "codereview_select":
                line = data.get("line")
                if (
                    state.current_activity == ActivityType.CODEREVIEW
                    and state.codereview_phase == "selecting"
                    and state.codereview_snippet is not None
                    and isinstance(line, int)
                    and 0 <= line < len(state.codereview_snippet.splitlines())
                ):
                    if pid not in state.codereview_selections:
                        state.codereview_selections[pid] = set()
                    state.codereview_selections[pid].add(line)
                    await broadcast_state()

            elif msg_type == "emoji_reaction":
                emoji = str(data.get("emoji", "")).strip()
                if emoji and len(emoji) <= 4:
                    await send_emoji_to_overlay(emoji)
                    await send_emoji_to_host(emoji)

            elif msg_type == "codereview_deselect":
                line = data.get("line")
                if (
                    state.current_activity == ActivityType.CODEREVIEW
                    and state.codereview_phase == "selecting"
                    and isinstance(line, int)
                ):
                    if pid in state.codereview_selections:
                        state.codereview_selections[pid].discard(line)
                    await broadcast_state()

            elif msg_type == "paste_text":
                text = str(data.get("text", ""))
                if text and len(text) <= 102400 and not is_host:  # 100KB limit
                    entries = state.paste_texts.setdefault(pid, [])
                    if len(entries) < 10:  # max 10 pending per participant
                        state.paste_next_id += 1
                        entries.append({"id": state.paste_next_id, "text": text})
                        await broadcast_participant_update()

            elif msg_type == "paste_dismiss":
                if is_host:
                    target_uuid = str(data.get("uuid", ""))
                    paste_id = data.get("paste_id")
                    if target_uuid in state.paste_texts and paste_id is not None:
                        state.paste_texts[target_uuid] = [
                            e for e in state.paste_texts[target_uuid] if e["id"] != paste_id
                        ]
                        if not state.paste_texts[target_uuid]:
                            del state.paste_texts[target_uuid]
                        await broadcast_participant_update()

            elif msg_type == "submit_feedback":
                text = str(data.get("text", "")).strip()
                if text and len(text) <= 2000 and not is_host:
                    state.feedback_pending.append(text)

    except WebSocketDisconnect:
        state.participants.pop(pid, None)
        state.locations.pop(pid, None)
        state.vote_times.pop(pid, None)
        state.participant_ips.pop(pid, None)
        ws_connections_active.labels(role=role).dec()
        # Keep participant_names and scores (persist for session)
        logger.info(f"Disconnected: {pid} ({len(state.participants)} remaining)")
        await broadcast_participant_update()


@router.websocket("/ws/{participant_id}")
async def websocket_endpoint(websocket: WebSocket, participant_id: str):
    """WebSocket endpoint for participants, host (__host__), and overlay (__overlay__).

    Also accepts regular participants directly (without session_id).
    """
    pid = participant_id.strip()
    is_host = pid == "__host__"
    is_overlay = pid == "__overlay__"

    await _handle_participant_connection(websocket, pid, is_host, is_overlay)


@session_router.websocket("/ws/{session_id}/{participant_id}")
async def session_websocket_endpoint(websocket: WebSocket, session_id: str, participant_id: str):
    """WebSocket endpoint for regular participants, requiring a valid session_id."""
    # Validate session_id — accept first so client gets a clean 1008 close code
    if not state.session_id or session_id.lower() != state.session_id.lower():
        await websocket.accept()
        await websocket.close(code=1008)
        return

    pid = participant_id.strip()
    if not pid or pid.startswith("__"):
        await websocket.accept()
        await websocket.close(code=1008)
        return

    await _handle_participant_connection(websocket, pid, is_host=False, is_overlay=False)
