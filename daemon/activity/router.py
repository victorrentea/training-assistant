"""Daemon activity router — host-only endpoint for switching current activity."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.participant.state import participant_state

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None

_VALID_ACTIVITIES = {"none", "poll", "wordcloud", "qa", "codereview", "debate"}


def set_ws_client(client):
    """Set the WebSocket client for broadcasting events."""
    global _ws_client
    _ws_client = client


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/activity') which expands to /api/{session_id}/activity.

host_router = APIRouter(prefix="/api/{session_id}/host/activity", tags=["activity"])


@host_router.post("")
async def set_activity(request: Request):
    """Host switches the current activity."""
    body = await request.json()
    activity = str(body.get("activity", "")).strip().lower()

    if activity not in _VALID_ACTIVITIES:
        return JSONResponse(
            {"error": f"Invalid activity '{activity}'. Must be one of: {sorted(_VALID_ACTIVITIES)}"},
            status_code=400,
        )

    participant_state.current_activity = activity

    if _ws_client:
        _ws_client.send({
            "type": "broadcast",
            "event": {"type": "activity_updated", "current_activity": activity},
        })

    return JSONResponse({"ok": True, "current_activity": activity})
