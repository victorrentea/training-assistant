from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from messaging import broadcast_state
from state import state

router = APIRouter()


class SummaryUpdate(BaseModel):
    points: list[str]


@router.post("/api/summary")
async def update_summary(body: SummaryUpdate):
    state.summary_points = body.points
    state.summary_updated_at = datetime.now(timezone.utc)
    await broadcast_state()
    return {"ok": True}


@router.post("/api/summary/force")
async def force_summary():
    state.summary_force_requested = True
    return {"ok": True}


@router.get("/api/summary/force")
async def poll_summary_force():
    requested = state.summary_force_requested
    state.summary_force_requested = False
    return {"requested": requested}
