"""Poll endpoints — host-only (called directly on daemon localhost).

No participant router yet; participant rendering is a follow-up.
"""
import logging

from fastapi import APIRouter, Response

from daemon.poll.state import PollData, poll_state

logger = logging.getLogger(__name__)


host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


@host_router.put("/update", status_code=204)
async def update_poll(body: PollData):
    """Host pushes the latest draft of the poll composer."""
    poll_state.data = body
    logger.debug("← poll/update: %r (%d options, multi=%s)", body.question, len(body.options), body.multi)
    return Response(status_code=204)
