"""Daemon misc router — participant + host endpoints for paste, notes, summary, slides cache."""
import logging
import threading
from typing import Optional, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.email_notify import notify as email_notify
from daemon.misc.content_files import read_notes_content, read_summary_payload
from daemon.misc.state import misc_state
from daemon.participant.state import participant_state
from daemon.session import state as session_shared_state
from daemon.ws_messages import PasteReceivedMsg, TranscriptionLanguagePendingMsg
from daemon.ws_publish import host_event, broadcast

logger = logging.getLogger(__name__)

# Pending transcription language request (read by daemon loop or macos-addons polling)
_transcription_language_lock = threading.Lock()
_transcription_language_pending: str | None = None


# ── Pydantic models ──

class OkResponse(BaseModel):
    ok: bool = True

class PasteRequest(BaseModel):
    text: str

class FeedbackRequest(BaseModel):
    text: str

class NotesResponse(BaseModel):
    notes_content: Optional[str] = None

class SummaryResponse(BaseModel):
    points: list = []
    raw_markdown: Optional[str] = None
    updated_at: Optional[str] = None

class SlidesCacheStatusResponse(BaseModel):
    slides_cache_status: Any = None

class TranscriptionLanguageRequest(BaseModel):
    language: str

class TranscriptionLanguageResponse(BaseModel):
    request: Optional[str] = None


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant", tags=["misc"])


@participant_router.post("/paste")
async def paste_text(request: Request, body: PasteRequest):
    """Participant pastes text to be seen by host."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    text = body.text
    if not text or len(text) > 102400:  # 100KB limit
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    entry = misc_state.add_paste(pid, text)
    if entry is None:
        return JSONResponse({"error": "Paste limit reached (max 10)"}, status_code=409)

    # Send only to host (not broadcast to all participants)
    request.state.write_back_events = [
        host_event(PasteReceivedMsg(uuid=pid, **entry)),
    ]

    return OkResponse()


@participant_router.post("/misc/feedback")
async def participant_feedback(request: Request, body: FeedbackRequest):
    """Participant feedback submitted from floating feedback modal."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    text = (body.text or "").strip()
    if not text or len(text) > 5000:
        return JSONResponse({"error": "Invalid feedback text"}, status_code=400)

    session_name = _get_session_name_for_feedback() or "unknown"
    participant_name = participant_state.participant_names.get(pid, pid)
    email_notify(
        f"Participant Feedback ({session_name})",
        f"Participant: {participant_name}\nSession: {session_name}\n\n{text}",
    )
    logger.info("Feedback received from participant %s", pid)
    return OkResponse()


def _get_session_name_for_feedback() -> str | None:
    """Return session name from misc cache, with session stack fallback."""
    if misc_state.session_name:
        return misc_state.session_name
    stack = session_shared_state.get_session_stack()
    return stack[-1]["name"] if stack else None


@participant_router.get("/notes")
async def get_notes():
    """Get session notes content."""
    return NotesResponse(notes_content=read_notes_content())


@participant_router.get("/summary")
async def get_summary():
    """Get summary points and raw markdown."""
    summary = read_summary_payload()
    return SummaryResponse(
        points=summary["points"],
        raw_markdown=summary["raw_markdown"],
        updated_at=summary["updated_at"],
    )


@participant_router.get("/slides-cache-status")
async def get_slides_cache_status():
    """Get slides cache status."""
    return SlidesCacheStatusResponse(slides_cache_status=misc_state.slides_cache_status)


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host", tags=["misc"])


@host_router.get("/pastes")
async def get_pastes():
    """Return all pending paste entries grouped by participant uuid."""
    return JSONResponse({"pastes": misc_state.paste_texts})


@host_router.get("/notes")
async def get_host_notes():
    """Return current session notes content."""
    return NotesResponse(notes_content=read_notes_content())


@host_router.get("/summary")
async def get_host_summary():
    """Return summary points, raw markdown, and updated_at timestamp."""
    summary = read_summary_payload()
    return SummaryResponse(
        points=summary["points"],
        raw_markdown=summary["raw_markdown"],
        updated_at=summary["updated_at"],
    )


# ── Global router (no session_id prefix) — used for transcription language ──

global_router = APIRouter(prefix="/api", tags=["misc"])

VALID_LANGUAGES = {"ro", "en", "auto"}


@global_router.post("/transcription-language")
async def set_transcription_language(body: TranscriptionLanguageRequest):
    """Host sets the transcription language — stores pending request for daemon/macos-addons."""
    global _transcription_language_pending
    lang = body.language.lower().strip()
    if lang not in VALID_LANGUAGES:
        return JSONResponse({"error": "language must be 'ro', 'en', or 'auto'"}, status_code=400)
    with _transcription_language_lock:
        _transcription_language_pending = lang
    broadcast(TranscriptionLanguagePendingMsg(language=lang))
    return OkResponse()


@global_router.get("/transcription-language/request")
async def poll_transcription_language_request():
    """Daemon/macos-addons polls for a pending language change request (clears on read)."""
    global _transcription_language_pending
    with _transcription_language_lock:
        req = _transcription_language_pending
        _transcription_language_pending = None
    return TranscriptionLanguageResponse(request=req)
