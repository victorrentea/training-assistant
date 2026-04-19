"""Poll endpoints — participant (proxied via Railway) + host (daemon localhost)."""
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.participant.state import participant_state
from daemon.poll.state import poll_state
from daemon.scores import scores
from daemon.ws_messages import (
    ActivityUpdatedMsg,
    PollAiGeneratedMsg,
    PollClearedMsg,
    PollClosedMsg,
    PollCorrectRevealedMsg,
    PollOpenedMsg,
    PollTimerStartedMsg,
    ScoresUpdatedMsg,
    VoteUpdateMsg,
)
from daemon.ws_publish import broadcast, broadcast_event, notify_host

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class VoteRequest(BaseModel):
    options: list[int]

class CreatePollRequest(BaseModel):
    question: str
    options: list[str]
    multi: bool
    correct_count: Optional[int] = None

class ClosePollResponse(BaseModel):
    vote_counts: list[int]

class RevealCorrectRequest(BaseModel):
    correct_indices: list[int] = []

class StartTimerRequest(BaseModel):
    seconds: int = 30

class SetPollStatusRequest(BaseModel):
    open: bool

# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/poll", tags=["poll"])


@participant_router.post("/vote", status_code=204)
async def cast_vote(request: Request, body: VoteRequest):
    """Participant casts a vote."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing participant ID"}, status_code=400)

    accepted = poll_state.cast_vote(pid, option_indices=body.options)
    if not accepted:
        return JSONResponse({"error": "Vote rejected"}, status_code=409)

    vote_msg = VoteUpdateMsg(vote_counts=poll_state.vote_counts())
    request.state.write_back_events = [broadcast_event(vote_msg)]
    await notify_host(vote_msg)
    return Response(status_code=204)


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


@host_router.post("/manual/submit", status_code=204)
async def create_poll(body: CreatePollRequest):
    """Host manually creates a new poll."""
    activity = participant_state.current_activity
    if activity and activity not in ("none", "poll"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)

    poll = poll_state.create_poll(
        body.question,
        body.options,
        body.multi,
        body.correct_count,
    )
    participant_state.current_activity = "poll"

    await notify_host(PollAiGeneratedMsg(poll=poll))
    return Response(status_code=204)


@host_router.post("/open", status_code=204)
async def open_poll():
    """Host opens the poll for voting."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    poll_state.open_poll(scores.snapshot_base)
    broadcast(PollOpenedMsg(poll=poll_state.poll))
    await notify_host(PollOpenedMsg(poll=poll_state.poll))
    return Response(status_code=204)


@host_router.post("/close", response_model=ClosePollResponse)
async def close_poll():
    """Host closes the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.close_poll()
    closed_msg = PollClosedMsg(vote_counts=result["vote_counts"])
    broadcast(closed_msg)
    await notify_host(closed_msg)
    return ClosePollResponse(**result)


@host_router.put("/correct", status_code=204)
async def reveal_correct(body: RevealCorrectRequest):
    """Host reveals correct answers and awards scores."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.reveal_correct(body.correct_indices, scores)
    broadcast(PollCorrectRevealedMsg(correct_indices=result["correct_indices"]))
    broadcast(ScoresUpdatedMsg(scores=result["scores"]))
    await notify_host(PollCorrectRevealedMsg(correct_indices=result["correct_indices"]))
    await notify_host(ScoresUpdatedMsg(scores=result["scores"]))
    return Response(status_code=204)


@host_router.post("/end/timer", status_code=204)
async def start_timer(body: StartTimerRequest):
    """Host starts a countdown timer for the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.start_timer(body.seconds)
    broadcast(PollTimerStartedMsg(seconds=result["seconds"]))
    await notify_host(PollTimerStartedMsg(seconds=result["seconds"]))
    return Response(status_code=204)


@host_router.put("/status", response_model=ClosePollResponse)
async def set_poll_status(body: SetPollStatusRequest):
    """Compatibility: {open: true} → open_poll, {open: false} → close_poll."""
    if body.open:
        return await open_poll()
    else:
        return await close_poll()


@host_router.delete("", status_code=204)
async def delete_poll():
    """Host deletes the current poll."""
    poll_state.clear()
    participant_state.current_activity = "none"
    broadcast(PollClearedMsg())
    broadcast(ActivityUpdatedMsg(current_activity="none"))
    await notify_host(PollClearedMsg())
    return Response(status_code=204)
