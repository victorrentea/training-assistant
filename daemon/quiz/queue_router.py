"""Poll queue router — host-only endpoints for pre-submitted poll questions."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.quiz.queue import quiz_queue
from daemon.ws_messages import PollQueueUpdatedMsg
from daemon.ws_publish import notify_host

logger = logging.getLogger(__name__)

_LOG = "qz-queue"


# ── Pydantic models ──

class PollQueueQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]


class SubmitQuestionsRequest(BaseModel):
    questions: list[PollQueueQuestion]


# ── Router ──

router = APIRouter(prefix="/api/{session_id}/host/poll/queue", tags=["poll"])


@router.post("", status_code=204)
async def submit_questions(body: SubmitQuestionsRequest):
    """Replace the entire poll queue with the submitted questions."""
    questions = [q.model_dump() for q in body.questions]
    quiz_queue.submit(questions)
    daemon_log.info(_LOG, f"Queue submitted: {len(questions)} question(s)")
    await notify_host(PollQueueUpdatedMsg())
    return Response(status_code=204)


@router.delete("/{index}", status_code=204)
async def remove_from_queue(index: int):
    """Remove the question at the given 0-based index from the queue."""
    try:
        removed = quiz_queue.all_items()[index]
        quiz_queue.remove(index)
    except IndexError:
        return JSONResponse({"error": f"No item at index {index}"}, status_code=404)
    await notify_host(PollQueueUpdatedMsg())
    daemon_log.info(_LOG, f"Removed queue item [{index}]: \"{removed['question'][:60]}\" — {quiz_queue.pending_count()} remaining")
    return Response(status_code=204)


@router.delete("", status_code=204)
async def clear_queue():
    """Clear the entire quiz queue."""
    quiz_queue.clear()
    await notify_host(PollQueueUpdatedMsg())
    daemon_log.info(_LOG, "Queue cleared")
    return Response(status_code=204)
