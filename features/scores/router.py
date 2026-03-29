from fastapi import APIRouter, Depends

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state

router = APIRouter()


@router.delete("/api/scores", dependencies=[Depends(require_host_auth)])
async def reset_scores():
    state.scores = {}
    state.base_scores = {}
    await broadcast_state()
    return {"ok": True}


@router.delete("/api/scores/{uuid}", dependencies=[Depends(require_host_auth)])
async def reset_score(uuid: str):
    state.scores.pop(uuid, None)
    state.base_scores.pop(uuid, None)
    await broadcast_state()
    return {"ok": True}
