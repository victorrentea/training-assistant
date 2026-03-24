from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from messaging import broadcast_state
from state import state

router = APIRouter()
public_router = APIRouter()


class SummaryPoint(BaseModel):
    text: str
    source: str = "discussion"  # "notes" or "discussion"
    time: str | None = None  # approximate HH:MM timestamp from transcript


class SummaryUpdate(BaseModel):
    points: list[SummaryPoint]


@router.post("/api/summary")
async def update_summary(body: SummaryUpdate):
    state.summary_points = [p.model_dump() for p in body.points]
    state.summary_updated_at = datetime.now(timezone.utc)
    await broadcast_state()
    return {"ok": True}


class NotesUpdate(BaseModel):
    content: str


@router.post("/api/notes")
async def update_notes(body: NotesUpdate):
    state.notes_content = body.content
    await broadcast_state()
    return {"ok": True}


# Public endpoints — no auth required
@public_router.get("/api/summary")
async def get_summary():
    return {
        "points": state.summary_points,
        "updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
    }


@public_router.get("/api/notes")
async def get_notes():
    return {
        "content": state.notes_content,
        "summary_points": state.summary_points,
        "summary_updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
    }


class TranscriptStatus(BaseModel):
    line_count: int
    total_lines: int = 0
    latest_ts: str | None = None


@router.post("/api/transcript-status")
async def update_transcript_status(body: TranscriptStatus):
    state.transcript_line_count = body.line_count
    state.transcript_total_lines = body.total_lines
    state.transcript_latest_ts = body.latest_ts
    await broadcast_state()
    return {"ok": True}


_last_force_at: float = 0.0
_FORCE_COOLDOWN = 30.0  # seconds — ignore rapid requests


@public_router.post("/api/summary/force")
async def force_summary():
    import time
    global _last_force_at
    now = time.monotonic()
    if now - _last_force_at < _FORCE_COOLDOWN:
        return {"ok": True, "cooldown": True}
    _last_force_at = now
    state.summary_force_requested = True
    return {"ok": True}


@router.get("/api/summary/force")
async def poll_summary_force():
    requested = state.summary_force_requested
    state.summary_force_requested = False
    return {"requested": requested}


@router.post("/api/token-usage")
async def update_token_usage(data: dict):
    state.token_usage = data
    await broadcast_state()
    return {"ok": True}
