"""Leaderboard show/hide and score reset — host-facing endpoints."""
from fastapi import APIRouter, Response
from pydantic import BaseModel

from daemon.leaderboard.state import leaderboard_state
from daemon.participant.state import participant_state
from daemon.scores import scores
from daemon.ws_messages import LeaderboardRevealedMsg, ScoresUpdatedMsg
from daemon.ws_publish import broadcast, notify_host


class LeaderboardPosition(BaseModel):
    rank: int
    name: str
    score: int


class ShowLeaderboardResponse(BaseModel):
    entries: list[LeaderboardPosition]


router = APIRouter(prefix="/api/{session_id}/host", tags=["leaderboard"])


@router.post("/leaderboard/show", response_model=ShowLeaderboardResponse)
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
    entries = [
        LeaderboardPosition(rank=i + 1, name=e["name"], score=e["score"])
        for i, e in enumerate(raw_entries)
    ]
    broadcast(LeaderboardRevealedMsg(positions=[e.model_dump() for e in entries]))
    return ShowLeaderboardResponse(entries=entries)


@router.delete("/scores", status_code=204)
async def reset_scores():
    was_empty = not scores.snapshot()
    scores.reset()
    if not was_empty:
        msg = ScoresUpdatedMsg(scores=scores.snapshot())
        broadcast(msg)
        await notify_host(msg)
    return Response(status_code=204)
