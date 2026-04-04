"""Poll endpoints — participant (proxied via Railway) + host (daemon localhost)."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.poll.state import poll_state
from daemon.scores import scores
from daemon.host_ws import send_to_host
from daemon.participant.state import participant_state

logger = logging.getLogger(__name__)

_ws_client = None


def set_ws_client(client):
    """Set the WebSocket client for broadcasting events."""
    global _ws_client
    _ws_client = client


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/poll", tags=["poll"])


@participant_router.post("/vote")
async def cast_vote(request: Request):
    """Participant casts a vote."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing participant ID"}, status_code=400)

    body = await request.json()
    option_ids = body.get("option_ids")

    accepted = poll_state.cast_vote(pid, option_ids=option_ids)
    if not accepted:
        return JSONResponse({"error": "Vote rejected"}, status_code=409)

    return JSONResponse({"ok": True})


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/poll') which expands to /api/{session_id}/poll.

host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


@host_router.post("")
async def create_poll(request: Request):
    """Host creates a new poll."""
    body = await request.json()
    question = body.get("question", "")
    options = body.get("options", [])
    multi = body.get("multi", False)
    correct_count = body.get("correct_count")

    # Activity gate
    activity = participant_state.current_activity
    if activity and activity not in ("none", "poll"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)

    poll = poll_state.create_poll(question, options, multi, correct_count)
    participant_state.current_activity = "poll"

    # Only notify host — participants see nothing until opened
    await send_to_host({"type": "poll_created", "poll": poll})
    return JSONResponse({"ok": True, "poll": poll})


@host_router.post("/open")
async def open_poll(request: Request):
    """Host opens the poll for voting."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    poll_state.open_poll(scores.snapshot_base)
    _broadcast({"type": "poll_opened", "poll": poll_state.poll})
    await send_to_host({"type": "poll_opened", "poll": poll_state.poll})
    return JSONResponse({"ok": True})


@host_router.post("/close")
async def close_poll(request: Request):
    """Host closes the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    result = poll_state.close_poll()
    _broadcast({"type": "poll_closed", **result})
    await send_to_host({"type": "poll_closed", **result})
    return JSONResponse({"ok": True, **result})


@host_router.put("/correct")
async def reveal_correct(request: Request):
    """Host reveals correct answers and awards scores."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    body = await request.json()
    correct_ids = body.get("correct_ids", [])
    result = poll_state.reveal_correct(correct_ids, scores)
    _broadcast({"type": "poll_correct_revealed", **result})
    _broadcast({"type": "scores_updated", "scores": result["scores"]})
    await send_to_host({"type": "poll_correct_revealed", **result})
    await send_to_host({"type": "scores_updated", "scores": result["scores"]})
    return JSONResponse({"ok": True})


@host_router.post("/timer")
async def start_timer(request: Request):
    """Host starts a countdown timer for the poll."""
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)

    body = await request.json()
    seconds = body.get("seconds", 30)
    result = poll_state.start_timer(seconds)
    _broadcast({"type": "poll_timer_started", **result})
    await send_to_host({"type": "poll_timer_started", **result})
    return JSONResponse({"ok": True})


@host_router.delete("")
async def delete_poll(request: Request):
    """Host deletes the current poll."""
    poll_state.clear()
    participant_state.current_activity = "none"
    _broadcast({"type": "poll_cleared"})
    _broadcast({"type": "activity_updated", "current_activity": "none"})
    await send_to_host({"type": "poll_cleared"})
    return JSONResponse({"ok": True})


# ── Quiz history (public) ──

quiz_md_router = APIRouter(tags=["quiz"])


@quiz_md_router.get("/api/{session_id}/quiz-md")
async def get_quiz_md():
    """Return the accumulated quiz markdown history."""
    return JSONResponse({"content": poll_state.quiz_md_content})


# ── Broadcast helper ──

def _broadcast(event: dict):
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": event})
