import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from messaging import broadcast, build_state_message
from state import state, ActivityType

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_POINTS = 1000
_MIN_POINTS = 500
_SPEED_WINDOW = 30  # seconds over which speed bonus applies


class PollCreate(BaseModel):
    question: str
    options: list[str]
    multi: bool = False
    correct_count: Optional[int] = None

class PollTimer(BaseModel):
    seconds: int


class PollOpen(BaseModel):
    open: bool


class PollCorrect(BaseModel):
    correct_ids: list[str]


@router.post("/api/poll")
async def create_poll(poll: PollCreate):
    if not poll.question.strip():
        raise HTTPException(400, "Question cannot be empty")
    if len(poll.options) < 2:
        raise HTTPException(400, "Need at least 2 options")
    if len(poll.options) > 8:
        raise HTTPException(400, "Maximum 8 options")
    if state.current_activity not in (ActivityType.NONE, ActivityType.POLL):
        raise HTTPException(409, "Another activity is already active")

    state.poll = {
        "question": poll.question.strip(),
        "multi": poll.multi,
        "correct_count": poll.correct_count if poll.multi else None,
        "options": [
            {"id": f"opt{i}", "text": opt.strip()}
            for i, opt in enumerate(poll.options)
            if opt.strip()
        ],
    }
    state.current_activity = ActivityType.POLL
    state.poll_active = False
    state.votes = {}

    await broadcast(build_state_message())
    return {"ok": True, "poll": state.poll}


@router.post("/api/poll/status")
async def set_poll_status(body: PollOpen):
    if not state.poll:
        raise HTTPException(400, "No poll created yet")
    state.poll_active = body.open
    if body.open:
        state.poll_opened_at = datetime.now(timezone.utc)
        state.vote_times = {}
        state.base_scores = dict(state.scores)
    await broadcast(build_state_message())
    return {"ok": True, "poll_active": state.poll_active}


@router.post("/api/poll/correct")
async def set_correct_options(body: PollCorrect):
    if not state.poll:
        raise HTTPException(400, "No active poll")
    correct_set = set(body.correct_ids)
    now = datetime.now(timezone.utc)
    opened_at = state.poll_opened_at or now

    multi = state.poll.get("multi", False)
    total_options = len(state.poll.get("options", []))
    all_option_ids = {opt["id"] for opt in state.poll.get("options", [])}
    wrong_set = all_option_ids - correct_set

    new_scores = dict(state.base_scores)
    for name, selection in state.votes.items():
        voted = set(selection) if isinstance(selection, list) else {selection}
        if multi and correct_set:
            # Proportional (R - W) / C, floored at 0
            R = len(voted & correct_set)   # correct options selected
            W = len(voted & wrong_set)     # wrong options selected
            C = len(correct_set)
            ratio = max(0.0, (R - W) / C)
            if ratio == 0:
                continue
        else:
            # Single-select: must match exactly
            if not (voted & correct_set):
                continue
            ratio = 1.0

        elapsed = (state.vote_times.get(name, now) - opened_at).total_seconds()
        elapsed = max(0, min(elapsed, _SPEED_WINDOW))
        max_pts = round(_MAX_POINTS * (1 - 0.5 * elapsed / _SPEED_WINDOW))
        max_pts = max(max_pts, _MIN_POINTS)
        pts = round(max_pts * ratio)
        if pts > 0:
            new_scores[name] = new_scores.get(name, 0) + pts

    state.scores = new_scores
    await broadcast({"type": "scores", "scores": state.scores})

    for name, ws in list(state.participants.items()):
        if name == "__host__":
            continue
        selection = state.votes.get(name)
        if selection is None:
            continue
        voted = set(selection) if isinstance(selection, list) else {selection}
        await ws.send_text(json.dumps({
            "type": "result",
            "correct_ids": list(correct_set),
            "voted_ids": list(voted),
            "score": state.scores.get(name, 0),
        }))

    return {"ok": True}


@router.post("/api/poll/timer")
async def start_poll_timer(body: PollTimer):
    """Host starts a countdown; broadcasts timer to all clients."""
    if not state.poll_active:
        raise HTTPException(400, "Poll is not open")
    if not (1 <= body.seconds <= 120):
        raise HTTPException(400, "seconds must be 1–120")
    started_at = datetime.now(timezone.utc)
    await broadcast({"type": "timer", "seconds": body.seconds, "started_at": started_at.isoformat()})
    return {"ok": True}


@router.delete("/api/poll")
async def clear_poll():
    state.poll = None
    state.poll_active = False
    state.votes = {}
    state.base_scores = dict(state.scores)
    state.vote_times = {}
    state.current_activity = ActivityType.NONE
    await broadcast(build_state_message())
    return {"ok": True}


@router.get("/api/suggest-name")
async def suggest_name():
    return {"name": state.suggest_name()}


@router.get("/api/status")
async def status():
    return {
        "participants": len(state.participants),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "total_votes": len(state.votes),
    }
