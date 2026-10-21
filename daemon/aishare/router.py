"""AI-share endpoints — host controls + participant answers.

Host flow: Start (everyone is routed to the Activity view with the survey) →
optionally Reveal (everyone sees every question's answers, anonymously) → Clear.
"""
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from daemon.aishare.state import MAX_OTHER_LEN, MAX_VALUE, QUESTIONS, aishare_state, valid_value
from daemon.participant.state import participant_state
from daemon.ws_messages import (
    ActivityUpdatedMsg,
    AiShareHostUpdateMsg,
    AiShareOpenedMsg,
    AiShareQuestion,
    AiShareResult,
    AiShareUpdatedMsg,
)
from daemon.ws_publish import broadcast, notify_host

logger = logging.getLogger(__name__)

ACTIVITY = "aishare"


class AiShareHostState(BaseModel):
    active: bool
    revealed: bool
    questions: list[AiShareQuestion]
    results: list[AiShareResult]


class RevealRequest(BaseModel):
    revealed: bool


class AiShareValueRequest(BaseModel):
    question: str = "ai_generated"
    value: int = Field(ge=0, le=MAX_VALUE,
                       description="slider: 0..100; choice: the option index; multi: bitmask of the ticked options (0 = none)")
    other: str | None = Field(default=None, max_length=MAX_OTHER_LEN,
                              description='free text typed after picking the question\'s "other" option')
    hearts: int = Field(default=0, ge=0,
                        description="multi: bitmask of the ❤️ favourite options, among the ticked ones (0 = none)")


def _questions() -> list[AiShareQuestion]:
    return [AiShareQuestion.model_validate(q) for q in QUESTIONS]


def _results() -> list[AiShareResult]:
    return [AiShareResult.model_validate(r) for r in aishare_state.results()]


def participant_view() -> dict:
    """What any participant may see: everyone's answers only once revealed."""
    results = aishare_state.results()
    if not aishare_state.revealed:
        results = [{"id": r["id"], "count": r["count"]} for r in results]
    # What people typed under "Other" goes to the host only.
    results = [{k: v for k, v in r.items() if k != "others"} for r in results]
    return {
        "active": aishare_state.active,
        "revealed": aishare_state.revealed,
        "questions": QUESTIONS,
        "results": results,
    }


def _host_state() -> dict:
    return {"active": aishare_state.active, "revealed": aishare_state.revealed,
            "questions": _questions(), "results": _results()}


async def _push_state() -> None:
    broadcast(AiShareUpdatedMsg(**participant_view()))
    await notify_host(AiShareHostUpdateMsg(**_host_state()))


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host/aishare", tags=["aishare"])


@host_router.get("", response_model=AiShareHostState)
async def get_aishare():
    """Host snapshot fetch on tab activation. Subsequent updates via WS."""
    return AiShareHostState(**_host_state())


@host_router.post("/start", status_code=204)
async def start_aishare():
    """Open a fresh round and route every participant to the survey."""
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
    """Participant answers one question; the last value wins."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)
    if not valid_value(body.question, body.value):
        return JSONResponse({"error": "Unknown question or value out of range"}, status_code=422)
    if not aishare_state.set_value(pid, body.question, body.value, body.other, body.hearts):
        return JSONResponse({"error": "AI share not active"}, status_code=409)
    await _push_state()
    return Response(status_code=204)
