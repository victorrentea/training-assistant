import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from messaging import broadcast, build_state_message, send_state_to, participant_names
from state import state

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/{participant_name}")
async def websocket_endpoint(websocket: WebSocket, participant_name: str):
    name = participant_name.strip()[:32]
    if not name:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    state.participants[name] = websocket
    state.suggested_names.discard(name)
    logger.info(f"Connected: {name} ({len(state.participants)} total)")

    await send_state_to(websocket)

    names = participant_names()
    await broadcast({"type": "participant_count", "count": len(names), "names": names})

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "location":
                loc = str(data.get("location", "")).strip()[:80]
                if loc:
                    state.locations[name] = loc
                    names = participant_names()
                    await broadcast({
                        "type": "participant_count",
                        "count": len(names),
                        "names": names,
                        "locations": {n: state.locations.get(n, "") for n in names},
                    })

            elif data.get("type") == "vote":
                option_id = data.get("option_id")
                valid_ids = [o["id"] for o in state.poll["options"]] if state.poll else []
                if state.poll_active and state.poll and not state.poll.get("multi") and option_id in valid_ids:
                    state.votes[name] = option_id
                    if name not in state.vote_times:
                        state.vote_times[name] = datetime.now(timezone.utc)
                    await broadcast({
                        "type": "vote_update",
                        "vote_counts": state.vote_counts(),
                        "total_votes": len(state.votes),
                    })

            elif data.get("type") == "multi_vote":
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
                    and len(set(option_ids)) == len(option_ids)  # no duplicates
                    and all(oid in valid_ids for oid in option_ids)
                ):
                    state.votes[name] = option_ids
                    if name not in state.vote_times:
                        state.vote_times[name] = datetime.now(timezone.utc)
                    await broadcast({
                        "type": "vote_update",
                        "vote_counts": state.vote_counts(),
                        "total_votes": len(state.votes),
                    })

    except WebSocketDisconnect:
        state.participants.pop(name, None)
        state.locations.pop(name, None)
        state.vote_times.pop(name, None)
        logger.info(f"Disconnected: {name} ({len(state.participants)} remaining)")
        names = participant_names()
        await broadcast({
            "type": "participant_count",
            "count": len(names),
            "names": names,
            "locations": {n: state.locations.get(n, "") for n in names},
        })
