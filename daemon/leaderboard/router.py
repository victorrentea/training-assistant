"""Leaderboard show/hide and score reset — host-facing endpoints."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.scores import scores
from daemon.participant.state import participant_state
from daemon.host_ws import send_to_host
from daemon.leaderboard.state import leaderboard_state

_ws_client = None


def set_ws_client(client):
    global _ws_client
    _ws_client = client


class OkResponse(BaseModel):
    ok: bool = True


router = APIRouter(prefix="/api/{session_id}/host", tags=["leaderboard"])


@router.post("/leaderboard/show")
async def show_leaderboard():
    all_scores = scores.snapshot()
    entries = [
        {
            "uuid": pid,
            "name": participant_state.participant_names.get(pid, "???"),
            "score": sc,
        }
        for pid, sc in sorted(all_scores.items(), key=lambda x: -x[1])
        if sc > 0
    ][:5]
    total = len([s for s in all_scores.values() if s > 0])
    leaderboard_state.show(entries, total)
    payload = {"type": "leaderboard_revealed", "entries": entries, "total_participants": total}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return OkResponse()


@router.delete("/scores")
async def reset_scores():
    scores.reset()
    payload = {"type": "scores_updated", "scores": scores.snapshot()}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return OkResponse()
