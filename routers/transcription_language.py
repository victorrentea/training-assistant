from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from messaging import broadcast
from state import state

router = APIRouter()


class LanguageRequest(BaseModel):
    language: str  # "ro" | "en" | "auto"


@router.post("/api/transcription-language")
async def set_transcription_language(body: LanguageRequest):
    lang = body.language.lower().strip()
    if lang not in ("ro", "en", "auto"):
        from fastapi import HTTPException
        raise HTTPException(400, "language must be 'ro', 'en', or 'auto'")
    state.transcription_language_request = lang
    await broadcast({"type": "transcription_language_pending", "language": lang})
    return {"ok": True}


@router.get("/api/transcription-language/request")
async def poll_transcription_language_request():
    state.daemon_last_seen = datetime.now(timezone.utc)
    req = state.transcription_language_request
    state.transcription_language_request = None
    return {"request": req}


class LanguageStatus(BaseModel):
    language: str


@router.post("/api/transcription-language/status")
async def transcription_language_status(body: LanguageStatus):
    state.transcription_language = body.language
    await broadcast({"type": "transcription_language", "language": body.language})
    return {"ok": True}
