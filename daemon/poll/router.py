"""Poll endpoints — participant (proxied via Railway) + host (daemon localhost)."""
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.poll.state import poll_state
from daemon.scores import scores
from daemon.participant.state import participant_state
from daemon.ws_publish import broadcast, notify_host
from daemon.ws_messages import (
    PollAiGeneratedMsg, PollOpenedMsg, PollClosedMsg, PollCorrectRevealedMsg,
    PollClearedMsg, PollTimerStartedMsg, ScoresUpdatedMsg, ActivityUpdatedMsg,
)

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class OkResponse(BaseModel):
    ok: bool = True

class VoteRequest(BaseModel):
    option_ids: list[str]

class CreatePollRequest(BaseModel):
    question: str = ""
    options: list[dict] = []
    multi: bool = False
    correct_count: Optional[int] = None

class CreatePollResponse(BaseModel):
    ok: bool = True
    poll: dict

class RevealCorrectRequest(BaseModel):
    correct_ids: list[str] = []

class StartTimerRequest(BaseModel):
    seconds: int = 30

class QuizMdResponse(BaseModel):
    content: str


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/poll", tags=["poll"])


@participant_router.post("/vote")
async def cast_vote(request: Request, body: VoteRequest):
    """Participant casts a vote."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing participant ID"}, status_code=400)

    accepted = poll_state.cast_vote(pid, option_ids=body.option_ids)
    if not accepted:
        return JSONResponse({"error": "Vote rejected"}, status_code=409)

    return OkResponse()


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/poll') which expands to /api/{session_id}/poll.

host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


@host_router.post("")
async def create_poll(body: CreatePollRequest):
    """Host creates a new poll."""
    # Activity gate
    activity = participant_state.current_activity
    if activity and activity not in ("none", "poll"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)

    poll = poll_state.create_poll(body.question, body.options, body.multi, body.correct_count)
    participant_state.current_activity = "poll"

    # Only notify host — participants see nothing until opened
    await notify_host(PollAiGeneratedMsg(poll=poll))
    return CreatePollResponse(poll=poll)


@host_router.post("/open")
async def open_poll():
    """Host opens the poll for voting."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    poll_state.open_poll(scores.snapshot_base)
    broadcast(PollOpenedMsg(poll=poll_state.poll))
    await notify_host(PollOpenedMsg(poll=poll_state.poll))
    return OkResponse()


@host_router.post("/close")
async def close_poll():
    """Host closes the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.close_poll()
    broadcast(PollClosedMsg())
    await notify_host(PollClosedMsg())
    return JSONResponse({"ok": True, **result})


@host_router.put("/correct")
async def reveal_correct(body: RevealCorrectRequest):
    """Host reveals correct answers and awards scores."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.reveal_correct(body.correct_ids, scores)
    broadcast(PollCorrectRevealedMsg(correct_ids=result["correct_ids"]))
    broadcast(ScoresUpdatedMsg(scores=result["scores"]))
    await notify_host(PollCorrectRevealedMsg(correct_ids=result["correct_ids"]))
    await notify_host(ScoresUpdatedMsg(scores=result["scores"]))
    return OkResponse()


@host_router.post("/timer")
async def start_timer(body: StartTimerRequest):
    """Host starts a countdown timer for the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.start_timer(body.seconds)
    broadcast(PollTimerStartedMsg(seconds=result["seconds"]))
    await notify_host(PollTimerStartedMsg(seconds=result["seconds"]))
    return OkResponse()


@host_router.delete("")
async def delete_poll():
    """Host deletes the current poll."""
    poll_state.clear()
    participant_state.current_activity = "none"
    broadcast(PollClearedMsg())
    broadcast(ActivityUpdatedMsg(current_activity="none"))
    await notify_host(PollClearedMsg())
    return OkResponse()


# ── Quiz history (public) ──

quiz_md_router = APIRouter(tags=["quiz"])


@quiz_md_router.get("/api/{session_id}/quiz-md")
async def get_quiz_md():
    """Return the accumulated quiz markdown history."""
    return QuizMdResponse(content=poll_state.quiz_md_content)
