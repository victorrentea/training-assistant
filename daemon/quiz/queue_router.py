"""Poll queue router — host-only endpoints for pre-submitted poll questions."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.participant.state import participant_state
from daemon.poll.state import poll_state
from daemon.quiz.queue import quiz_queue
from daemon.scores import scores
from daemon.ws_messages import PollAiGeneratedMsg, PollOpenedMsg
from daemon.ws_publish import broadcast, notify_host

logger = logging.getLogger(__name__)

_LOG = "qz-queue"


# ── Pydantic models ──

class PollQueueQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]


class SubmitQuestionsRequest(BaseModel):
    questions: list[PollQueueQuestion]


class PollQueueStatusResponse(BaseModel):
    pending: int
    current: PollQueueQuestion | None


class OkResponse(BaseModel):
    ok: bool = True


# ── Router ──

router = APIRouter(prefix="/api/{session_id}/host/poll-queue", tags=["poll-queue"])


@router.post("", response_model=OkResponse)
async def submit_questions(body: SubmitQuestionsRequest):
    """Replace the entire poll queue with the submitted questions. Typically called by AI submitting generated questions."""
    questions = [q.model_dump() for q in body.questions]
    quiz_queue.submit(questions)
    daemon_log.info(_LOG, f"Queue submitted: {len(questions)} question(s)")
    return OkResponse()


@router.get("", response_model=PollQueueStatusResponse)
async def get_queue_status():
    """Return how many questions are pending and what the current question looks like."""
    current = quiz_queue.current()
    current_model = PollQueueQuestion.model_validate(current) if current else None
    return PollQueueStatusResponse(
        pending=quiz_queue.pending_count(),
        current=current_model,
    )


@router.post("/fire", response_model=OkResponse)
async def fire_current():
    """Fire the current question as a poll and advance the queue."""
    current = quiz_queue.current()
    if current is None:
        return JSONResponse({"error": "Poll queue is empty"}, status_code=400)

    # Activity gate — same pattern as poll router
    activity = participant_state.current_activity
    if activity and activity not in ("none", "poll"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)

    options = current["options"]  # already list[str]
    correct_count = len(current["correct_indices"])
    multi = correct_count > 1

    poll = poll_state.create_poll(
        question=current["question"],
        options=options,
        multi=multi,
        correct_count=correct_count if multi else None,
    )
    participant_state.current_activity = "poll"

    poll_state.open_poll(scores.snapshot_base)

    broadcast(PollOpenedMsg(poll=poll))
    await notify_host(PollAiGeneratedMsg(poll=poll))
    await notify_host(PollOpenedMsg(poll=poll))

    quiz_queue.advance()
    daemon_log.info(_LOG, f"Fired question: \"{current['question'][:60]}\" — {quiz_queue.pending_count()} remaining")
    return OkResponse()


@router.post("/skip", response_model=OkResponse)
async def skip_current():
    """Skip the current question without firing it."""
    current = quiz_queue.current()
    if current is None:
        return JSONResponse({"error": "Poll queue is empty"}, status_code=400)

    quiz_queue.advance()
    daemon_log.info(_LOG, f"Skipped question: \"{current['question'][:60]}\" — {quiz_queue.pending_count()} remaining")
    return OkResponse()


@router.delete("", response_model=OkResponse)
async def clear_queue():
    """Clear the entire quiz queue."""
    quiz_queue.clear()
    daemon_log.info(_LOG, "Queue cleared")
    return OkResponse()
