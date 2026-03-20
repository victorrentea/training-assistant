from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from messaging import broadcast_state
from state import state

router = APIRouter()


class SummaryPoint(BaseModel):
    text: str
    source: str = "discussion"  # "notes" or "discussion"


class SummaryUpdate(BaseModel):
    points: list[SummaryPoint]


@router.post("/api/summary")
async def update_summary(body: SummaryUpdate):
    state.summary_points = [p.model_dump() for p in body.points]
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
