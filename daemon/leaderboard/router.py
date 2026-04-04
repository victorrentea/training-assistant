"""Leaderboard show/hide and score reset — host-facing endpoints."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from daemon.scores import scores
from daemon.participant.state import participant_state
from daemon.host_ws import send_to_host

_ws_client = None


def set_ws_client(client):
    global _ws_client
    _ws_client = client


router = APIRouter(prefix="/api/{session_id}", tags=["leaderboard"])


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
    payload = {"type": "leaderboard_revealed", "entries": entries, "total_participants": total}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return JSONResponse({"ok": True})


@router.post("/leaderboard/hide")
async def hide_leaderboard():
    payload = {"type": "leaderboard_hide"}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return JSONResponse({"ok": True})


@router.delete("/scores")
async def reset_scores():
    scores.reset()
    payload = {"type": "scores_updated", "scores": scores.snapshot()}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return JSONResponse({"ok": True})
