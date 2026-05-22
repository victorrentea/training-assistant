"""Quiz endpoints — participant (proxied via Railway) + host (daemon localhost)."""
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.participant.state import participant_state
from daemon.quiz.state import quiz_state
from daemon.scores import scores
from daemon.ws_messages import (
    ActivityUpdatedMsg,
    QuizClearedMsg,
    QuizCorrectRevealedMsg,
    QuizEndCountdownStartedMsg,
    QuizEndedMsg,
    QuizOpenedMsg,
    ScoresUpdatedMsg,
    VoteUpdateMsg,
)
from daemon.ws_publish import broadcast, broadcast_event, notify_host

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class VoteRequest(BaseModel):
    options: list[int]

class CreateQuizRequest(BaseModel):
    question: str
    options: list[str]
    multi: bool
    correct_count: Optional[int] = None


class RevealCorrectRequest(BaseModel):
    correct_indices: list[int]

class StartTimerRequest(BaseModel):
    seconds: int = 30

class HostQuizVote(BaseModel):
    option_indices: list[int]
    voted_at: str

class QueuedQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]


class QuizQueueStatus(BaseModel):
    pending: int
    items: list[QueuedQuestion]
    current: QueuedQuestion | None = None  # always items[0] if non-empty

class HostQuizStateResponse(BaseModel):
    id: str | None = None
    question: str | None = None
    options: list[str] | None = None
    multi: bool | None = None
    correct_count: int | None = None
    end_timer_seconds: int | None = None
    end_timer_started_at: str | None = None
    correct_indices: list[int] | None = None
    quiz_running: bool
    votes: dict[str, HostQuizVote]
    queue: QuizQueueStatus

# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/quiz", tags=["quiz"])


@participant_router.post("/vote", status_code=204)
async def cast_vote(request: Request, body: VoteRequest):
    """Participant casts a vote."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing participant ID"}, status_code=400)

    accepted = quiz_state.cast_vote(pid, option_indices=body.options)
    if not accepted:
        return JSONResponse({"error": "Vote rejected"}, status_code=409)

    vote_msg = VoteUpdateMsg(voted_count=len(quiz_state.votes))
    request.state.write_back_events = [broadcast_event(vote_msg)]
    await notify_host(vote_msg)
    return Response(status_code=204)


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host/quiz", tags=["quiz"])


@host_router.post("/manual/submit", status_code=204)
async def create_quiz(body: CreateQuizRequest):
    """Host manually creates and immediately opens a new quiz."""
    activity = participant_state.current_activity
    if activity and activity not in ("none", "quiz"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)

    quiz_state.create_quiz(
        body.question,
        body.options,
        body.multi,
        body.correct_count,
    )
    participant_state.current_activity = "quiz"
    quiz_state.open_quiz(scores.snapshot_base)

    assert quiz_state.quiz is not None  # set by create_quiz above
    broadcast(QuizOpenedMsg(quiz=quiz_state.quiz))
    await notify_host(QuizOpenedMsg(quiz=quiz_state.quiz))
    return Response(status_code=204)


@host_router.post("/end", status_code=204)
async def end_quiz():
    """Host ends the quiz."""
    if not quiz_state.quiz:
        return JSONResponse({"error": "No quiz"}, status_code=400)

    quiz_state.close_quiz()
    ended_msg = QuizEndedMsg()
    broadcast(ended_msg)
    await notify_host(ended_msg)
    return Response(status_code=204)


@host_router.put("/correct", status_code=204)
async def reveal_correct(body: RevealCorrectRequest):
    """Host reveals correct answers and awards scores."""
    if not quiz_state.quiz:
        return JSONResponse({"error": "No quiz"}, status_code=400)

    result = quiz_state.reveal_correct(body.correct_indices, scores)
    broadcast(QuizCorrectRevealedMsg(correct_indices=result["correct_indices"]))
    broadcast(ScoresUpdatedMsg(scores=result["scores"]))
    await notify_host(QuizCorrectRevealedMsg(correct_indices=result["correct_indices"]))
    await notify_host(ScoresUpdatedMsg(scores=result["scores"]))
    return Response(status_code=204)


@host_router.post("/end/timer", status_code=204)
async def start_timer(body: StartTimerRequest):
    """Host starts a countdown timer to end the quiz."""
    if not quiz_state.quiz:
        return JSONResponse({"error": "No quiz"}, status_code=400)

    result = quiz_state.start_timer(body.seconds)
    msg = QuizEndCountdownStartedMsg(seconds=result["seconds"], started_at=result["started_at"])
    broadcast(msg)
    await notify_host(msg)
    return Response(status_code=204)


@host_router.delete("", status_code=204)
async def delete_quiz():
    """Host deletes the current quiz."""
    quiz_state.clear()
    participant_state.current_activity = "none"
    broadcast(QuizClearedMsg())
    broadcast(ActivityUpdatedMsg(current_activity="none"))
    await notify_host(QuizClearedMsg())
    return Response(status_code=204)


@host_router.get("", response_model=HostQuizStateResponse)
async def get_quiz_state():
    """Return full quiz state for host quiz tab."""
    from daemon.quiz_queue.queue import quiz_queue
    ps = quiz_state
    p = ps.quiz
    _queue_current = quiz_queue.current()
    return HostQuizStateResponse(
        id=p["id"] if p else None,
        question=p["question"] if p else None,
        options=p["options"] if p else None,
        multi=p.get("multi") if p else None,
        correct_count=p.get("correct_count") if p else None,
        end_timer_seconds=ps.quiz_timer_seconds,
        end_timer_started_at=ps.quiz_timer_started_at.isoformat() if ps.quiz_timer_started_at else None,
        correct_indices=ps.quiz_correct_indices,
        quiz_running=ps.quiz_active,
        votes={pid: HostQuizVote(**v) for pid, v in ps.votes.items()},
        queue=QuizQueueStatus(
            pending=quiz_queue.pending_count(),
            items=[QueuedQuestion(**q) for q in quiz_queue.all_items()],
            current=QueuedQuestion(**_queue_current) if _queue_current else None,
        ),
    )
