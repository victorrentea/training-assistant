"""Daemon activity router — host-only endpoint for switching current activity."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.participant.state import participant_state
from daemon.ws_publish import broadcast
from daemon.ws_messages import ActivityUpdatedMsg

logger = logging.getLogger(__name__)

_VALID_ACTIVITIES = {"none", "poll", "wordcloud", "qa", "codereview", "debate"}


# ── Pydantic models ──

class SetActivityRequest(BaseModel):
    activity: str

class SetActivityResponse(BaseModel):
    ok: bool = True
    current_activity: str


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/activity') which expands to /api/{session_id}/activity.

host_router = APIRouter(prefix="/api/{session_id}/host/activity", tags=["activity"])


@host_router.put("")
async def set_activity(body: SetActivityRequest):
    """Host switches the current activity."""
    activity = body.activity.strip().lower()

    if activity not in _VALID_ACTIVITIES:
        return JSONResponse(
            {"error": f"Invalid activity '{activity}'. Must be one of: {sorted(_VALID_ACTIVITIES)}"},
            status_code=400,
        )

    participant_state.current_activity = activity

    broadcast(ActivityUpdatedMsg(current_activity=activity))

    return SetActivityResponse(current_activity=activity)
