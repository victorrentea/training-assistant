"""Daemon misc router — participant + host endpoints for paste, notes, summary, slides cache."""
import logging
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.misc.state import misc_state

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None

# Pending transcription language request (read by daemon loop or macos-addons polling)
_transcription_language_lock = threading.Lock()
_transcription_language_pending: str | None = None


def set_ws_client(client):
    """Set the WebSocket client for broadcasting events."""
    global _ws_client
    _ws_client = client


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant", tags=["misc"])


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

    # Send only to host (not broadcast to all participants)
    request.state.write_back_events = [
        {"type": "send_to_host", "event": {"type": "paste_received", "uuid": pid, **entry}},
    ]

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

host_router = APIRouter(prefix="/api/{session_id}/host", tags=["misc"])


@host_router.post("/paste-dismiss")
async def paste_dismiss(request: Request):
    """Host dismisses a paste entry by participant uuid and paste id."""
    body = await request.json()
    target_uuid = str(body.get("uuid", ""))
    paste_id = body.get("paste_id")

    if not target_uuid or paste_id is None:
        return JSONResponse({"error": "Missing uuid or paste_id"}, status_code=400)

    misc_state.dismiss_paste(target_uuid, str(paste_id))

    if _ws_client is not None:
        _ws_client.send({
            "type": "broadcast",
            "event": {"type": "paste_dismissed", "uuid": target_uuid, "paste_id": paste_id},
        })

    return JSONResponse({"ok": True})


@host_router.get("/pastes")
async def get_pastes():
    """Return all pending paste entries grouped by participant uuid."""
    return JSONResponse({"pastes": misc_state.paste_texts})


# ── Global router (no session_id prefix) — used for transcription language ──

global_router = APIRouter(prefix="/api", tags=["misc"])

VALID_LANGUAGES = {"ro", "en", "auto"}


@global_router.post("/transcription-language")
async def set_transcription_language(request: Request):
    """Host sets the transcription language — stores pending request for daemon/macos-addons."""
    global _transcription_language_pending
    body = await request.json()
    lang = str(body.get("language", "")).lower().strip()
    if lang not in VALID_LANGUAGES:
        return JSONResponse({"error": "language must be 'ro', 'en', or 'auto'"}, status_code=400)
    with _transcription_language_lock:
        _transcription_language_pending = lang
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": {"type": "transcription_language_pending", "language": lang}})
    return JSONResponse({"ok": True})


@global_router.get("/transcription-language/request")
async def poll_transcription_language_request():
    """Daemon/macos-addons polls for a pending language change request (clears on read)."""
    global _transcription_language_pending
    with _transcription_language_lock:
        req = _transcription_language_pending
        _transcription_language_pending = None
    return JSONResponse({"request": req})
