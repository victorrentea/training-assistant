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

from messaging import (
    broadcast,
    broadcast_state,
    broadcast_participant_update,
    build_participant_state,
    send_state_to_participant,
    send_state_to_host,
    send_emoji_to_overlay,
    send_emoji_to_host,
)
from metrics import (
    ws_connections_active,
    ws_messages_total,
    poll_votes_total,
    poll_vote_duration_seconds,
    qa_questions_total,
    qa_upvotes_total,
)
from state import state, ActivityType, assign_avatar, refresh_avatar
from messaging import participant_ids
from routers.debate import auto_assign_remaining

router = APIRouter()
logger = logging.getLogger(__name__)


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

    try:
        while True:
            data = await websocket.receive_json()
            state.daemon_last_seen = datetime.now(timezone.utc)
            msg_type = data.get("type")
            if msg_type == "slides_upload_result":
                from routers.slides import register_daemon_upload_result

                await register_daemon_upload_result(data)
            elif msg_type == "daemon_ping":
                # Heartbeat message; last_seen already updated.
                continue
    except WebSocketDisconnect:
        pass
    finally:
        if state.daemon_ws is websocket:
            state.daemon_ws = None
        logger.info("Daemon WS disconnected")


@router.websocket("/ws/{participant_id}")
async def websocket_endpoint(websocket: WebSocket, participant_id: str):
    pid = participant_id.strip()
    if not pid:
        await websocket.close(code=1008)
        return

    is_host = pid == "__host__"
    is_overlay = pid == "__overlay__"
    role = "host" if is_host else ("overlay" if is_overlay else "participant")

    # Overlay reconnect: kick old overlay connection
    if is_overlay and "__overlay__" in state.participants:
        old_ws = state.participants["__overlay__"]
        try:
            await old_ws.send_text(json.dumps({"type": "kicked"}))
            await old_ws.close(code=1001)
        except Exception:
            pass
        del state.participants["__overlay__"]

    # Host reconnect: kick old host connection
    if is_host and "__host__" in state.participants:
        old_ws = state.participants["__host__"]
        try:
            await old_ws.send_text(json.dumps({"type": "kicked"}))
            await old_ws.close(code=1001)
        except Exception:
            pass
        del state.participants["__host__"]

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
                    for_count = sum(1 for s in state.debate_sides.values() if s == "for")
                    against_count = sum(1 for s in state.debate_sides.values() if s == "against")
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

            elif msg_type == "wordcloud_word":
                word = str(data.get("word", "")).strip().lower()
                if state.current_activity == ActivityType.WORDCLOUD and word:
                    if word not in state.wordcloud_words:
                        state.wordcloud_word_order.insert(0, word)
                    state.wordcloud_words[word] = state.wordcloud_words.get(word, 0) + 1
                    if not is_host:
                        state.scores[pid] = state.scores.get(pid, 0) + 200
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
                    state.scores[pid] = state.scores.get(pid, 0) + 100
                    qa_questions_total.inc()
                    await broadcast_state()

            elif msg_type == "qa_upvote":
                question_id = data.get("question_id")
                q = state.qa_questions.get(question_id)
                if q and q["author"] != pid and pid not in q["upvoters"]:
                    q["upvoters"].add(pid)
                    author_pid = q["author"]
                    state.scores[author_pid] = state.scores.get(author_pid, 0) + 50
                    state.scores[pid] = state.scores.get(pid, 0) + 25
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
                        fc = sum(1 for s in state.debate_sides.values() if s == "for")
                        ac = sum(1 for s in state.debate_sides.values() if s == "against")
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
                    state.scores[pid] = state.scores.get(pid, 0) + 100
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
                            state.scores[arg["author_uuid"]] = state.scores.get(arg["author_uuid"], 0) + 50
                        state.scores[pid] = state.scores.get(pid, 0) + 25
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
                        state.scores[pid] = state.scores.get(pid, 0) + 2500
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


    except WebSocketDisconnect:
        state.participants.pop(pid, None)
        state.locations.pop(pid, None)
        state.vote_times.pop(pid, None)
        state.participant_ips.pop(pid, None)
        ws_connections_active.labels(role=role).dec()
        # Keep participant_names and scores (persist for session)
        logger.info(f"Disconnected: {pid} ({len(state.participants)} remaining)")
        await broadcast_participant_update()
