from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from core.messaging import broadcast
from core.state import state
from features.ws.daemon_protocol import push_to_daemon

router = APIRouter()
public_router = APIRouter()


class SummaryPoint(BaseModel):
    text: str
    source: str = "discussion"  # "notes" or "discussion"
    time: str | None = None  # approximate HH:MM timestamp from transcript


class SummaryUpdate(BaseModel):
    points: list[SummaryPoint]
    raw_markdown: str | None = None


@router.post("/summary")
async def update_summary(body: SummaryUpdate):
    state.summary_points = [p.model_dump() for p in body.points]
    if body.raw_markdown is not None:
        state.summary_raw_markdown = body.raw_markdown
    state.summary_updated_at = datetime.now(timezone.utc)
    await broadcast({"type": "summary", "points": state.summary_points,
                     "raw_markdown": state.summary_raw_markdown,
                     "updated_at": state.summary_updated_at.isoformat()})
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
        "raw_markdown": state.summary_raw_markdown,
        "summary_updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
    }


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
    await push_to_daemon({"type": "summary_force"})
    return {"ok": True}


@router.post("/summary/full-reset")
async def full_reset_summary():
    state.summary_reset_requested = True
    state.summary_force_requested = True
    await push_to_daemon({"type": "summary_full_reset"})
    return {"ok": True}


