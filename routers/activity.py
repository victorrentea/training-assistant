from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast, build_state_message
from state import state, ActivityType

router = APIRouter()


class ActivitySwitch(BaseModel):
    activity: str  # "poll" | "wordcloud" | "qa" | "none"


@router.post("/api/activity", dependencies=[Depends(require_host_auth)])
async def set_activity(body: ActivitySwitch):
    try:
        new_activity = ActivityType(body.activity)
    except ValueError:
        raise HTTPException(400, f"Unknown activity: {body.activity}")
    state.current_activity = new_activity
    await broadcast(build_state_message())
    return {"ok": True, "current_activity": new_activity}
