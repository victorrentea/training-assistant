"""Daemon misc router — participant + host endpoints for paste, feedback, notes, summary, slides cache."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.misc.state import misc_state

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None


def set_ws_client(client):
    """Set the WebSocket client for broadcasting events."""
    global _ws_client
    _ws_client = client


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/misc", tags=["misc"])


@participant_router.post("/paste")
async def paste_text(request: Request):
    """Participant pastes text to be seen by host."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    text = str(body.get("text", ""))
    if not text or len(text) > 102400:  # 100KB limit
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    entry = misc_state.add_paste(pid, text)
    if entry is None:
        return JSONResponse({"error": "Paste limit reached (max 10)"}, status_code=409)

    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "paste_received", "uuid": pid, **entry}},
    ]

    return JSONResponse({"ok": True})


@participant_router.post("/feedback")
async def submit_feedback(request: Request):
    """Participant submits feedback text."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 2000:
        return JSONResponse({"error": "Invalid feedback text"}, status_code=400)

    misc_state.add_feedback(text)
    return JSONResponse({"ok": True})


@participant_router.get("/notes")
async def get_notes(request: Request):
    """Get session notes content."""
    return JSONResponse({"notes_content": misc_state.notes_content})


@participant_router.get("/summary")
async def get_summary(request: Request):
    """Get summary points and raw markdown."""
    return JSONResponse({
        "points": misc_state.summary_points,
        "raw_markdown": misc_state.summary_raw_markdown,
        "updated_at": misc_state.summary_updated_at,
    })


@participant_router.get("/slides-cache-status")
async def get_slides_cache_status(request: Request):
    """Get slides cache status."""
    return JSONResponse({"slides_cache_status": misc_state.slides_cache_status})


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/misc/paste-dismiss') which expands to /api/{session_id}/misc/paste-dismiss.

host_router = APIRouter(prefix="/api/{session_id}/misc", tags=["misc"])


@host_router.post("/paste-dismiss")
async def paste_dismiss(request: Request):
    """Host dismisses a paste entry by participant uuid and paste id."""
    body = await request.json()
    target_uuid = str(body.get("uuid", ""))
    paste_id = body.get("paste_id")

    if not target_uuid or paste_id is None:
        return JSONResponse({"error": "Missing uuid or paste_id"}, status_code=400)

    misc_state.dismiss_paste(target_uuid, int(paste_id))

    if _ws_client is not None:
        _ws_client.send({
            "type": "broadcast",
            "event": {"type": "paste_dismissed", "uuid": target_uuid, "paste_id": paste_id},
        })

    return JSONResponse({"ok": True})
