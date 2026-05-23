"""Poll endpoints — host-only (called directly on daemon localhost).

Participant vote endpoint is also included here.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel as _BaseModel

from daemon.participant.state import participant_state
from daemon.poll.state import PollData, poll_state
from daemon.ws_messages import (
    ActivityUpdatedMsg,
    PollOpenedMsg,
    PollUpdatedMsg,
    PollHostUpdateMsg,
)
from daemon.ws_publish import broadcast, notify_host

logger = logging.getLogger(__name__)


host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


def _pax_snapshot() -> dict:
    """Build the participant-facing poll snapshot from poll_state.data."""
    assert poll_state.data is not None
    return {
        "question": poll_state.data.question,
        "options": list(poll_state.data.options),
        "multi": poll_state.data.multi,
        "public": poll_state.data.public,
    }


async def _push_poll_state() -> None:
    """Single source of truth for poll updates.

    Broadcasts PollUpdatedMsg to participants (counts gated by public),
    and notifies the host directly with PollHostUpdateMsg (always full
    counts). Caller is responsible for first-time signals like
    ActivityUpdatedMsg + PollOpenedMsg.
    """
    if poll_state.data is None:
        return
    counts = poll_state.vote_counts()
    voted = poll_state.distinct_voter_count()
    counts_for_pax = counts if poll_state.data.public else None
    snapshot = _pax_snapshot()

    broadcast(PollUpdatedMsg(poll=snapshot, counts=counts_for_pax))
    await notify_host(
        PollHostUpdateMsg(poll=snapshot, counts=counts, voted_count=voted)
    )


@host_router.get("")
async def get_poll():
    """Host snapshot fetch on tab activation. Subsequent updates via WS."""
    if poll_state.data is None:
        return {"poll": None, "started": False, "counts": [], "voted_count": 0}
    return {
        "poll": _pax_snapshot(),
        "started": poll_state.started,
        "counts": poll_state.vote_counts(),
        "voted_count": poll_state.distinct_voter_count(),
    }


@host_router.put("/update", status_code=204)
async def update_poll(body: PollData):
    """Host pushes latest draft. Validates option deletion + multi flip
    while running, wipes votes on multi flip, broadcasts updates."""
    prev = poll_state.data
    if poll_state.started and prev is not None:
        # Forbid option removal while running
        prev_nonempty = [o for o in prev.options if o.strip()]
        new_nonempty = [o for o in body.options if o.strip()]
        if len(new_nonempty) < len(prev_nonempty):
            return JSONResponse(
                {"error": "Cannot remove options while poll is running"},
                status_code=409,
            )
        # Multi flip wipes votes (per spec edge case)
        if prev.multi != body.multi:
            poll_state.votes.clear()

    poll_state.data = body
    poll_state.invalidate_counts()
    logger.debug(
        f"← poll/update q={body.question!r} opts={len(body.options)} "
        f"multi={body.multi} public={body.public}"
    )

    if poll_state.started:
        await _push_poll_state()
    return Response(status_code=204)


@host_router.post("/start", status_code=204)
async def start_poll():
    """Validate the draft, set started, broadcast open signals."""
    data = poll_state.data
    if data is None:
        return JSONResponse({"error": "No draft to start"}, status_code=409)
    if not data.question.strip():
        return JSONResponse({"error": "Question is empty"}, status_code=409)
    nonempty = [o for o in data.options if o.strip()]
    if len(nonempty) < 2:
        return JSONResponse(
            {"error": "Need at least 2 non-empty options"}, status_code=409
        )

    poll_state.started = True
    poll_state.opened_at = datetime.now(timezone.utc).isoformat()
    poll_state.votes.clear()
    poll_state.invalidate_counts()
    participant_state.current_activity = "poll"

    # Order matters: routing first, then session marker, then snapshot
    broadcast(ActivityUpdatedMsg(current_activity="poll"))
    broadcast(PollOpenedMsg())
    await notify_host(ActivityUpdatedMsg(current_activity="poll"))
    await _push_poll_state()
    return Response(status_code=204)


@host_router.post("/stop", status_code=204)
async def stop_poll():
    """Clear poll draft and votes; broadcast activity transition to none."""
    was_running = poll_state.started
    poll_state.reset()
    if was_running and participant_state.current_activity == "poll":
        participant_state.current_activity = "none"
    broadcast(ActivityUpdatedMsg(current_activity="none"))
    await notify_host(ActivityUpdatedMsg(current_activity="none"))
    return Response(status_code=204)


class PollVoteRequest(_BaseModel):
    options: list[int]


participant_router = APIRouter(prefix="/api/participant/poll", tags=["poll"])


@participant_router.post("/vote", status_code=204)
async def cast_poll_vote(request: Request, body: PollVoteRequest):
    """Participant casts/changes their vote. Empty list clears the vote."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing participant ID"}, status_code=400)

    accepted = poll_state.cast_vote(pid, body.options)
    if not accepted:
        return JSONResponse(
            {"error": "Vote rejected (poll not active, invalid indices, or multi-vote when single)"},
            status_code=409,
        )

    await _push_poll_state()
    return Response(status_code=204)
