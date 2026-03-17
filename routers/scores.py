from fastapi import APIRouter

from messaging import broadcast
from state import state

router = APIRouter()


@router.delete("/api/scores")
async def reset_scores():
    state.scores = {}
    state.base_scores = {}
    await broadcast({"type": "scores", "scores": state.scores})
    return {"ok": True}
