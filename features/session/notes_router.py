"""Public summary and notes endpoints — participant-facing, session-scoped."""
from fastapi import APIRouter

from core.state import state

public_router = APIRouter()


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
