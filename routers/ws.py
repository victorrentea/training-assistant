import json
import logging
import time
import uuid as uuid_mod
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from messaging import (
    broadcast,
    broadcast_state,
    broadcast_participant_update,
    send_state_to_participant,
    send_state_to_host,
)
from state import state, ActivityType

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/{participant_id}")
async def websocket_endpoint(websocket: WebSocket, participant_id: str):
    pid = participant_id.strip()
    if not pid:
        await websocket.close(code=1008)
        return

    is_host = pid == "__host__"

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
    state.participants[pid] = websocket

    if is_host:
        state.participant_names["__host__"] = "Host"
        logger.info(f"Host connected ({len(state.participants)} total)")
        await send_state_to_host(websocket)
        await broadcast_participant_update()
    else:
        # Participant: wait for set_name before sending state
        logger.info(f"WS connected: {pid} (awaiting set_name)")

    named = is_host  # host is always "named"

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            # Before named, only accept set_name
            if not named:
                if msg_type != "set_name":
                    continue
                name = str(data.get("name", "")).strip()[:32]
                if not name:
                    continue
                state.participant_names[pid] = name
                named = True
                logger.info(f"Named: {pid} -> {name} ({len(state.participants)} total)")
                await send_state_to_participant(websocket, pid)
                await broadcast_participant_update()
                continue

            if msg_type == "set_name":
                # Allow rename
                name = str(data.get("name", "")).strip()[:32]
                if name:
                    state.participant_names[pid] = name
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
                    await broadcast({
                        "type": "vote_update",
                        "vote_counts": state.vote_counts(),
                        "total_votes": len(state.votes),
                    })

            elif msg_type == "wordcloud_word":
                word = str(data.get("word", "")).strip().lower()
                if state.current_activity == ActivityType.WORDCLOUD and word:
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
                    await broadcast_state()

            elif msg_type == "qa_upvote":
                question_id = data.get("question_id")
                q = state.qa_questions.get(question_id)
                if q and q["author"] != pid and pid not in q["upvoters"]:
                    q["upvoters"].add(pid)
                    author_pid = q["author"]
                    state.scores[author_pid] = state.scores.get(author_pid, 0) + 50
                    state.scores[pid] = state.scores.get(pid, 0) + 25
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
        # Keep participant_names and scores (persist for session)
        logger.info(f"Disconnected: {pid} ({len(state.participants)} remaining)")
        await broadcast_participant_update()
