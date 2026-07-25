"""Leaderboard show/hide and score reset — host-facing endpoints."""
from fastapi import APIRouter, Response
from pydantic import BaseModel

from daemon.leaderboard.state import leaderboard_state
from daemon.participant.state import participant_state
from daemon.scores import scores
from daemon.ws_messages import LeaderboardRevealedMsg, ScoresUpdatedMsg
from daemon.ws_publish import broadcast, notify_host

_AVATAR_COLORS = ['#e74c3c','#e67e22','#f1c40f','#27ae60','#16a085','#2980b9','#8e44ad','#c0392b']


def _entry_color(pid: str) -> str:
    return _AVATAR_COLORS[sum(ord(c) for c in pid) % len(_AVATAR_COLORS)]


class LeaderboardPosition(BaseModel):
    rank: int
    name: str
    score: int
    avatar: str | None = None
    letter: str | None = None
    color: str | None = None
    universe: str | None = None


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
            avatar=participant_state.participant_avatars.get(e["uuid"]),
            letter=(e["name"][0].upper() if e["name"] else "?"),
            color=_entry_color(e["uuid"]),
            universe=participant_state.participant_universes.get(e["uuid"]) or None,
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
        await notify_host(ScoresUpdatedMsg(scores=scores.snapshot()))
    return Response(status_code=204)
