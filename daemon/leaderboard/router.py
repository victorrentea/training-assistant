"""Leaderboard show/hide and score reset — host-facing endpoints."""
from fastapi import APIRouter, Response
from pydantic import BaseModel

from daemon.leaderboard.state import leaderboard_state
from daemon.participant.state import participant_state
from daemon.scores import notify_host_scores, scores
from daemon.ws_messages import LeaderboardRevealedMsg, ScoresUpdatedMsg
from daemon.ws_publish import broadcast


class LeaderboardPosition(BaseModel):
    rank: int
    name: str
    score: int
    universe: str | None = None
    # Server-side truth: derived from who claimed trainer over loopback, never
    # inferred from the display string (which anyone could otherwise fake).
    is_trainer: bool = False


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
        LeaderboardPosition(
            rank=i + 1,
            name=e["name"],
            score=e["score"],
            universe=participant_state.participant_universes.get(e["uuid"]) or None,
            is_trainer=e["uuid"] in participant_state.trainer_pids,
        )
        for i, e in enumerate(raw_entries)
    ]
    broadcast(LeaderboardRevealedMsg(positions=[e.model_dump() for e in entries]))
    return ShowLeaderboardResponse(entries=entries)


@router.delete("/scores", status_code=204)
async def reset_scores():
    was_empty = not scores.snapshot()
    scores.reset()
    if not was_empty:
        # Participants get the UUID-free token-keyed map (empty after reset);
        # the trusted host keeps the UUID-keyed map.
        broadcast(ScoresUpdatedMsg(scores=scores.snapshot_tokenized()))
        await notify_host_scores()
    return Response(status_code=204)
