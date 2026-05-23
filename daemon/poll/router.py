"""Poll endpoints — host-only (called directly on daemon localhost).

No participant router yet; participant rendering is a follow-up.
"""
import logging

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from daemon.poll.state import PollData, poll_state

logger = logging.getLogger(__name__)


host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


@host_router.put("/update", status_code=204)
async def update_poll(body: PollData):
    """Host pushes the latest draft of the poll composer."""
    poll_state.data = body
    logger.debug("← poll/update: %r (%d options, multi=%s)", body.question, len(body.options), body.multi)
    return Response(status_code=204)


@host_router.post("/start", status_code=204)
async def start_poll():
    """Host opens the current draft as a live poll."""
    data = poll_state.data
    if data is None:
        return JSONResponse({"error": "No draft to start"}, status_code=409)
    if not data.question.strip():
        return JSONResponse({"error": "Question is empty"}, status_code=409)
    nonempty = [o for o in data.options if o.strip()]
    if len(nonempty) < 2:
        return JSONResponse({"error": "Need at least 2 non-empty options"}, status_code=409)

    poll_state.started = True
    logger.info("◆ poll started: %r (%d options, multi=%s)", data.question, len(nonempty), data.multi)
    return Response(status_code=204)
