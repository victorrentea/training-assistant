"""Leaderboard show/hide and score reset endpoints."""
from fastapi import APIRouter, Depends
from core.auth import require_host_auth
from core.state import state
from core.messaging import broadcast_leaderboard, broadcast, broadcast_state

router = APIRouter()


@router.post("/leaderboard/show", dependencies=[Depends(require_host_auth)])
async def show_leaderboard():
    state.leaderboard_active = True
    await broadcast_leaderboard()
    return {"ok": True}


@router.post("/leaderboard/hide", dependencies=[Depends(require_host_auth)])
async def hide_leaderboard():
    state.leaderboard_active = False
    await broadcast({"type": "leaderboard_hide"})
    return {"ok": True}


@router.delete("/scores", dependencies=[Depends(require_host_auth)])
async def reset_scores():
    state.scores = {}
    state.base_scores = {}
    await broadcast_state()
    return {"ok": True}
