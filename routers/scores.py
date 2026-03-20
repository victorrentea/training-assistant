from fastapi import APIRouter, Depends

from auth import require_host_auth
from messaging import broadcast_state
from state import state

router = APIRouter()


@router.delete("/api/scores", dependencies=[Depends(require_host_auth)])
async def reset_scores():
    state.scores = {}
    state.base_scores = {}
    await broadcast_state()
    return {"ok": True}
