"""Daemon quiz router — host-only endpoints for poll request/refine/preview."""
import logging
from typing import Optional

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon import quiz as _quiz_pkg  # noqa: F401 - ensure package is importable
from daemon.config import DEFAULT_TRANSCRIPT_MINUTES
from daemon.quiz import pending as quiz_pending
from daemon.ws_messages import PollPreviewMsg, PollStatusMsg
from daemon.ws_publish import broadcast

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class OkResponse(BaseModel):
    ok: bool = True

class PollRequestBody(BaseModel):
    minutes: Optional[int] = None
    topic: Optional[str] = None

class PollPreviewPayload(BaseModel):
    quiz: dict | None = None
    question: str | None = None
    options: list[str] | None = None
    multi: bool | None = None
    correct_indices: list[int] | None = None


class PollRefineRequest(BaseModel):
    target: str
    preview: Optional[PollPreviewPayload] = None


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/poll-request') which expands to /api/{session_id}/poll-request.

host_router = APIRouter(prefix="/api/{session_id}/host", tags=["poll"])


@host_router.post("/poll-request", status_code=204)
async def request_poll(body: PollRequestBody):
    """Host requests a poll — stores request for the orchestrator loop to pick up."""
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

    quiz_pending.put("poll_request", {"request": req})

    broadcast(PollStatusMsg(status="requested", message=msg))

    return Response(status_code=204)


@host_router.delete("/poll-preview", status_code=204)
async def clear_poll_preview():
    """Host clears the current poll preview."""
    from daemon.ws_publish import broadcast
    broadcast(PollPreviewMsg(poll=None))
    return Response(status_code=204)


@host_router.post("/poll-refine", status_code=204)
async def request_poll_refine(body: PollRefineRequest):
    """Host requests regeneration of a specific question or option."""
    if not body.target:
        return JSONResponse({"error": "Missing 'target'"}, status_code=400)

    quiz_pending.put("poll_refine", {"request": {"target": str(body.target)}, "preview": body.preview})

    label = "question" if body.target == "question" else "option"
    msg = f"Regenerating {label}…"

    broadcast(PollStatusMsg(status="generating", message=msg))

    return Response(status_code=204)
