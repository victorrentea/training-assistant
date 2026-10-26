"""AI-share endpoints — host controls + participant answers.

Host flow: Start (everyone is routed to the Activity view with the survey) →
optionally Reveal (everyone sees every question's answers, anonymously) → Clear.
The ranking question is live from the start: participants add items and 🔥
them, everyone watches the list re-order; the host may delete an item.
"""
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from daemon.aishare.state import (
    MAX_ITEM_LEN,
    MAX_OTHER_LEN,
    MAX_VALUE,
    QUESTIONS,
    aishare_state,
    valid_value,
)
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


class AiShareItemRequest(BaseModel):
    question: str = "devex_pain"
    text: str = Field(min_length=1, max_length=MAX_ITEM_LEN, description="the new item; the same text (case aside) just gets a 🔥")


class AiShareItemAdded(BaseModel):
    id: int


class AiShareVoteRequest(BaseModel):
    question: str = "devex_pain"
    item: int
    vote: int = Field(ge=0, le=1, description="1 = 🔥 (burns me too), 0 = take it back")


def _questions() -> list[AiShareQuestion]:
    return [AiShareQuestion.model_validate(q) for q in QUESTIONS]


def _results() -> list[AiShareResult]:
    return [AiShareResult.model_validate(r) for r in aishare_state.results()]


def participant_view() -> dict:
    """What any participant may see: everyone's answers only once revealed."""
    results = aishare_state.results()
    if not aishare_state.revealed:
        # A ranking stays visible: watching it re-order live is the point.
        results = [{k: v for k, v in r.items() if k in ("id", "count", "items")} for r in results]
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


@host_router.delete("/items/{question}/{item_id}", status_code=204)
async def delete_aishare_item(question: str, item_id: int):
    """Moderation: drop a ranking item (a preset or one a participant added) with its votes."""
    if not aishare_state.delete_item(question, item_id):
        return JSONResponse({"error": "No such item"}, status_code=404)
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


@participant_router.post("/item", response_model=AiShareItemAdded)
async def add_aishare_item(request: Request, body: AiShareItemRequest):
    """Participant adds a ranking item (and their 🔥 on it)."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)
    item_id = aishare_state.add_item(pid, body.question, body.text)
    if item_id is None:
        return JSONResponse({"error": "Not accepted: survey not active, unknown question or too many items"},
                            status_code=409)
    await _push_state()
    return AiShareItemAdded(id=item_id)


@participant_router.post("/vote", status_code=204)
async def vote_aishare_item(request: Request, body: AiShareVoteRequest):
    """Participant 🔥 a ranking item (it burns them too), or takes it back."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)
    if not aishare_state.vote(pid, body.question, body.item, body.vote):
        return JSONResponse({"error": "Not accepted: survey not active or no such item"}, status_code=409)
    await _push_state()
    return Response(status_code=204)
