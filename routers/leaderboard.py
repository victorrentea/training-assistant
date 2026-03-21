"""Leaderboard show/hide endpoints."""
from fastapi import APIRouter, Depends
from auth import require_host_auth
from state import state
from messaging import broadcast_leaderboard, broadcast

router = APIRouter()


@router.post("/api/leaderboard/show", dependencies=[Depends(require_host_auth)])
async def show_leaderboard():
    state.leaderboard_active = True
    await broadcast_leaderboard()
    return {"ok": True}


@router.post("/api/leaderboard/hide", dependencies=[Depends(require_host_auth)])
async def hide_leaderboard():
    state.leaderboard_active = False
    await broadcast({"type": "leaderboard_hide"})
    return {"ok": True}
