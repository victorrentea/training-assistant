from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state, ActivityType

router = APIRouter()


class ActivitySwitch(BaseModel):
    activity: str  # "poll" | "wordcloud" | "qa" | "debate" | "none"


@router.post("/api/activity", dependencies=[Depends(require_host_auth)])
async def set_activity(body: ActivitySwitch):
    try:
        new_activity = ActivityType(body.activity)
    except ValueError:
        raise HTTPException(400, f"Unknown activity: {body.activity}")
    state.current_activity = new_activity
    state.needs_restore = False
    await broadcast_state()
    return {"ok": True, "current_activity": new_activity}
