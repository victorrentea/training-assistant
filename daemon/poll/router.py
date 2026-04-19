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
    PollClearedMsg,
    PollCorrectRevealedMsg,
    PollEndCountdownStartedMsg,
    PollEndedMsg,
    PollOpenedMsg,
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

class EndPollResponse(BaseModel):
    vote_counts: list[int]

class RevealCorrectRequest(BaseModel):
    correct_indices: list[int]

class StartTimerRequest(BaseModel):
    seconds: int = 30

class HostPollVote(BaseModel):
    option_indices: list[int]
    voted_at: str

class PollQueueStatus(BaseModel):
    pending: int
    current: dict | None = None

class HostPollStateResponse(BaseModel):
    id: str | None = None
    question: str | None = None
    options: list[str] | None = None
    multi: bool | None = None
    correct_count: int | None = None
    end_timer_seconds: int | None = None
    end_timer_started_at: str | None = None
    correct_indices: list[int] | None = None
    poll_running: bool
    votes: dict[str, HostPollVote]
    queue: PollQueueStatus

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

    vote_msg = VoteUpdateMsg(voted_count=len(poll_state.votes))
    request.state.write_back_events = [broadcast_event(vote_msg)]
    await notify_host(vote_msg)
    return Response(status_code=204)


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


@host_router.post("/manual/submit", status_code=204)
async def create_poll(body: CreatePollRequest):
    """Host manually creates and immediately opens a new poll."""
    activity = participant_state.current_activity
    if activity and activity not in ("none", "poll"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)

    poll_state.create_poll(
        body.question,
        body.options,
        body.multi,
        body.correct_count,
    )
    participant_state.current_activity = "poll"
    poll_state.open_poll(scores.snapshot_base)

    broadcast(PollOpenedMsg(poll=poll_state.poll))
    await notify_host(PollOpenedMsg(poll=poll_state.poll))
    return Response(status_code=204)


@host_router.post("/end", status_code=204)
async def end_poll():
    """Host ends the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.close_poll()
    ended_msg = PollEndedMsg(vote_counts=result["vote_counts"])
    broadcast(ended_msg)
    await notify_host(ended_msg)
    return Response(status_code=204)


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
    """Host starts a countdown timer to end the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.start_timer(body.seconds)
    msg = PollEndCountdownStartedMsg(seconds=result["seconds"], started_at=result["started_at"])
    broadcast(msg)
    await notify_host(msg)
    return Response(status_code=204)


@host_router.delete("", status_code=204)
async def delete_poll():
    """Host deletes the current poll."""
    poll_state.clear()
    participant_state.current_activity = "none"
    broadcast(PollClearedMsg())
    broadcast(ActivityUpdatedMsg(current_activity="none"))
    await notify_host(PollClearedMsg())
    return Response(status_code=204)


@host_router.get("", response_model=HostPollStateResponse)
async def get_poll_state():
    """Return full poll state for host poll tab."""
    from daemon.quiz.queue import quiz_queue
    ps = poll_state
    p = ps.poll
    return HostPollStateResponse(
        id=p["id"] if p else None,
        question=p["question"] if p else None,
        options=p["options"] if p else None,
        multi=p.get("multi") if p else None,
        correct_count=p.get("correct_count") if p else None,
        end_timer_seconds=ps.poll_timer_seconds,
        end_timer_started_at=ps.poll_timer_started_at.isoformat() if ps.poll_timer_started_at else None,
        correct_indices=ps.poll_correct_indices,
        poll_running=ps.poll_active,
        votes={pid: HostPollVote(**v) for pid, v in ps.votes.items()},
        queue=PollQueueStatus(pending=quiz_queue.pending_count(), current=quiz_queue.current()),
    )
