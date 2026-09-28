"""AI-share endpoints — host controls + participant slider answer.

Host flow: Start (everyone is routed to the Activity view with a slider) →
optionally Reveal (everyone sees the whole distribution, with names) → Clear.
"""
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from daemon.aishare.state import MAX_VALUE, MIN_VALUE, aishare_state
from daemon.participant.state import participant_state
from daemon.ws_messages import (
    ActivityUpdatedMsg,
    AiShareHostUpdateMsg,
    AiShareOpenedMsg,
    AiSharePoint,
    AiShareUpdatedMsg,
)
from daemon.ws_publish import broadcast, notify_host

logger = logging.getLogger(__name__)

ACTIVITY = "aishare"


class AiShareHostState(BaseModel):
    active: bool
    revealed: bool
    points: list[AiSharePoint]


class RevealRequest(BaseModel):
    revealed: bool


class AiShareValueRequest(BaseModel):
    value: int = Field(ge=MIN_VALUE, le=MAX_VALUE)


def _points() -> list[dict]:
    return aishare_state.points(participant_state.participant_names)


def participant_view() -> dict:
    """What any participant may see: everyone's answers only once revealed."""
    points = _points()
    return {
        "active": aishare_state.active,
        "revealed": aishare_state.revealed,
        "count": len(points),
        "points": points if aishare_state.revealed else None,
    }


async def _push_state() -> None:
    broadcast(AiShareUpdatedMsg(**participant_view()))
    await notify_host(AiShareHostUpdateMsg(
        active=aishare_state.active, revealed=aishare_state.revealed, points=_points(),
    ))


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host/aishare", tags=["aishare"])


@host_router.get("", response_model=AiShareHostState)
async def get_aishare():
    """Host snapshot fetch on tab activation. Subsequent updates via WS."""
    return AiShareHostState(
        active=aishare_state.active, revealed=aishare_state.revealed, points=_points(),
    )


@host_router.post("/start", status_code=204)
async def start_aishare():
    """Open a fresh round and route every participant to the slider."""
    aishare_state.start()
    participant_state.current_activity = ACTIVITY
    # Order matters: routing first, then the "come look" signal, then the snapshot.
    broadcast(ActivityUpdatedMsg(current_activity=ACTIVITY))
    broadcast(AiShareOpenedMsg())
    await notify_host(ActivityUpdatedMsg(current_activity=ACTIVITY))
    await _push_state()
    return Response(status_code=204)


@host_router.post("/reveal", status_code=204)
async def reveal_aishare(body: RevealRequest):
    """Show (or hide) everyone's answers to all participants."""
    aishare_state.revealed = body.revealed
    await _push_state()
    return Response(status_code=204)


@host_router.post("/clear", status_code=204)
async def clear_aishare():
    aishare_state.reset()
    if participant_state.current_activity == ACTIVITY:
        participant_state.current_activity = "none"
        broadcast(ActivityUpdatedMsg(current_activity="none"))
        await notify_host(ActivityUpdatedMsg(current_activity="none"))
    await _push_state()
    return Response(status_code=204)


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/aishare", tags=["aishare"])


@participant_router.post("/value", status_code=204)
async def set_aishare_value(request: Request, body: AiShareValueRequest):
    """Participant moves their slider; the last value wins."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)
    if not aishare_state.set_value(pid, body.value):
        return JSONResponse({"error": "AI share not active"}, status_code=409)
    await _push_state()
    return Response(status_code=204)
