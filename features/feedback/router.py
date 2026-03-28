from fastapi import APIRouter, Depends
from core.auth import require_host_auth
from core.state import state

router = APIRouter()

@router.get("/api/feedback/pending", dependencies=[Depends(require_host_auth)])
async def get_pending_feedback():
    items = list(state.feedback_pending)
    state.feedback_pending.clear()
    return {"items": items}
