"""Daemon quiz router — host-only endpoints for quiz request/refine/preview."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon import quiz as _quiz_pkg  # noqa: ensure package is importable
from daemon.quiz import pending as quiz_pending
from daemon.config import DEFAULT_TRANSCRIPT_MINUTES

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None


def set_ws_client(client):
    """Set the WebSocket client for broadcasting events."""
    global _ws_client
    _ws_client = client


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/quiz-request') which expands to /api/{session_id}/quiz-request.

host_router = APIRouter(prefix="/api/{session_id}", tags=["quiz"])


@host_router.post("/quiz-request")
async def request_quiz(request: Request):
    """Host requests a quiz — stores request for the orchestrator loop to pick up."""
    body = await request.json()
    topic = body.get("topic")
    minutes = body.get("minutes")

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

    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": {"type": "quiz_status", "status": "requested", "message": msg}})

    return JSONResponse({"ok": True})


@host_router.delete("/quiz-preview")
async def clear_quiz_preview():
    """Host clears the current quiz preview."""
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": {"type": "quiz_preview", "quiz": None}})
    return JSONResponse({"ok": True})


@host_router.post("/quiz-refine")
async def request_quiz_refine(request: Request):
    """Host requests regeneration of a specific question or option."""
    body = await request.json()
    target = body.get("target")
    preview = body.get("preview")

    if not target:
        return JSONResponse({"error": "Missing 'target'"}, status_code=400)

    quiz_pending.put("quiz_refine", {"request": {"target": str(target)}, "preview": preview})

    label = "question" if target == "question" else "option"
    msg = f"Regenerating {label}…"

    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": {"type": "quiz_status", "status": "generating", "message": msg}})

    return JSONResponse({"ok": True})
