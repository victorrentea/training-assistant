"""Leaderboard show/hide and score reset — host-facing endpoints."""
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.scores import scores
from daemon.participant.state import participant_state
from daemon.leaderboard.state import leaderboard_state
from daemon.ws_publish import broadcast, notify_host
from daemon.ws_messages import LeaderboardRevealedMsg, LeaderboardHiddenMsg, ScoresUpdatedMsg


class OkResponse(BaseModel):
    ok: bool = True


router = APIRouter(prefix="/api/{session_id}/host", tags=["leaderboard"])


@router.post("/leaderboard/show", status_code=204)
async def show_leaderboard():
    all_scores = scores.snapshot()
    raw_entries = [
        {
            "uuid": pid,
            "name": participant_state.participant_names.get(pid, "???"),
            "score": sc,
        }
        for pid, sc in sorted(all_scores.items(), key=lambda x: -x[1])
        if sc > 0
    ][:5]
    total = len([s for s in all_scores.values() if s > 0])
    leaderboard_state.show(raw_entries, total)
    positions = [
        {"rank": i + 1, "name": e["name"], "score": e["score"]}
        for i, e in enumerate(raw_entries)
    ]
    msg = LeaderboardRevealedMsg(positions=positions)
    broadcast(msg)
    await notify_host(msg)
    return Response(status_code=204)


@router.post("/leaderboard/hide", status_code=204)
async def hide_leaderboard():
    leaderboard_state.reset()
    msg = LeaderboardHiddenMsg()
    broadcast(msg)
    await notify_host(msg)
    return Response(status_code=204)


@router.delete("/scores", status_code=204)
async def reset_scores():
    scores.reset()
    msg = ScoresUpdatedMsg(scores=scores.snapshot())
    broadcast(msg)
    await notify_host(msg)
    return Response(status_code=204)
