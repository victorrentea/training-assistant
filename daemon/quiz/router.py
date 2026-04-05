"""Daemon quiz router — host-only endpoints for quiz request/refine/preview."""
import logging
from typing import Optional, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon import quiz as _quiz_pkg  # noqa: ensure package is importable
from daemon.quiz import pending as quiz_pending
from daemon.config import DEFAULT_TRANSCRIPT_MINUTES
from daemon.ws_publish import broadcast
from daemon.ws_messages import QuizStatusMsg, QuizPreviewMsg

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class OkResponse(BaseModel):
    ok: bool = True

class QuizRequestBody(BaseModel):
    minutes: Optional[int] = None
    topic: Optional[str] = None

class QuizRefineRequest(BaseModel):
    target: str
    preview: Optional[Any] = None


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/quiz-request') which expands to /api/{session_id}/quiz-request.

host_router = APIRouter(prefix="/api/{session_id}/host", tags=["quiz"])


@host_router.post("/quiz-request")
async def request_quiz(body: QuizRequestBody):
    """Host requests a quiz — stores request for the orchestrator loop to pick up."""
    topic = body.topic
    minutes = body.minutes

    has_topic = bool(topic and str(topic).strip())
    has_minutes = minutes is not None and int(minutes) > 0

    if has_topic == has_minutes:
        return JSONResponse(
            {"error": "Provide either 'minutes' (transcript mode) or 'topic' (topic mode), not both or neither."},
            status_code=400,
        )

    if has_topic:
        req = {"minutes": None, "topic": str(topic).strip()}
        msg = f"Waiting for daemon (topic: {topic})…"
    else:
        minutes = int(minutes) if minutes else DEFAULT_TRANSCRIPT_MINUTES
        req = {"minutes": minutes, "topic": None}
        msg = f"Waiting for daemon (last {minutes} min)…"

    quiz_pending.put("quiz_request", {"request": req})

    broadcast(QuizStatusMsg(status="requested", message=msg))

    return OkResponse()


@host_router.delete("/quiz-preview")
async def clear_quiz_preview():
    """Host clears the current quiz preview."""
    # TODO: no model yet — QuizPreviewMsg requires question/options but clearing sends quiz=None
    from daemon import ws_publish as _pub
    if _pub._ws_client:
        _pub._ws_client.send({"type": "broadcast", "event": {"type": "quiz_preview", "quiz": None}})
    return OkResponse()


@host_router.post("/quiz-refine")
async def request_quiz_refine(body: QuizRefineRequest):
    """Host requests regeneration of a specific question or option."""
    if not body.target:
        return JSONResponse({"error": "Missing 'target'"}, status_code=400)

    quiz_pending.put("quiz_refine", {"request": {"target": str(body.target)}, "preview": body.preview})

    label = "question" if body.target == "question" else "option"
    msg = f"Regenerating {label}…"

    broadcast(QuizStatusMsg(status="generating", message=msg))

    return OkResponse()
