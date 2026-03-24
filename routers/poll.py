import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import require_host_auth
from backend_version import get_backend_version
from pydantic import BaseModel

from messaging import broadcast, broadcast_state, participant_ids
from state import state, ActivityType

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_POINTS = 1000
_MIN_POINTS = 500
_SLOWEST_MULTIPLIER = 3  # participant taking 3× the fastest time gets _MIN_POINTS


class PollCreate(BaseModel):
    question: str
    options: list[str]
    multi: bool = False
    correct_count: Optional[int] = None
    source: Optional[str] = None
    page: Optional[str] = None

class PollTimer(BaseModel):
    seconds: int


class PollOpen(BaseModel):
    open: bool


class PollCorrect(BaseModel):
    correct_ids: list[str]


@router.post("/api/poll", dependencies=[Depends(require_host_auth)])
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
        "id": int(datetime.now(timezone.utc).timestamp() * 1000),
        "question": poll.question.strip(),
        "multi": poll.multi,
        "correct_count": poll.correct_count if poll.multi else None,
        "options": [
            {"id": f"opt{i}", "text": opt.strip()}
            for i, opt in enumerate(poll.options)
            if opt.strip()
        ],
        "source": poll.source or None,
        "page": poll.page or None,
    }
    state.current_activity = ActivityType.POLL
    state.poll_active = False
    state.votes = {}
    state.poll_correct_ids = None

    await broadcast_state()
    return {"ok": True, "poll": state.poll}


@router.put("/api/poll/status", dependencies=[Depends(require_host_auth)])
async def set_poll_status(body: PollOpen):
    if not state.poll:
        raise HTTPException(400, "No poll created yet")
    state.poll_active = body.open
    if body.open:
        state.poll_opened_at = datetime.now(timezone.utc)
        state.vote_times = {}
        state.base_scores = dict(state.scores)
    else:
        state.poll_timer_seconds = None
        state.poll_timer_started_at = None
    await broadcast_state()
    return {"ok": True, "poll_active": state.poll_active}


@router.put("/api/poll/correct", dependencies=[Depends(require_host_auth)])
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

    # Compute min elapsed time among correct voters for Kahoot-style speed bonus
    correct_voters = set()
    for pid, selection in state.votes.items():
        voted = set(selection) if isinstance(selection, list) else {selection}
        if multi and correct_set:
            R = len(voted & correct_set)
            W = len(voted & wrong_set)
            if max(0.0, (R - W) / len(correct_set)) > 0:
                correct_voters.add(pid)
        else:
            if voted & correct_set:
                correct_voters.add(pid)

    elapsed_times = [
        max(0.0, (state.vote_times.get(n, now) - opened_at).total_seconds())
        for n in correct_voters
    ]
    min_time = min(elapsed_times) if elapsed_times else 0.0

    new_scores = dict(state.base_scores)
    for pid, selection in state.votes.items():
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

        elapsed = max(0.0, (state.vote_times.get(pid, now) - opened_at).total_seconds())
        # Linear from _MAX_POINTS (at min_time) to _MIN_POINTS (at _SLOWEST_MULTIPLIER × min_time)
        speed_window = min_time * (_SLOWEST_MULTIPLIER - 1)  # range over which decay applies
        if speed_window > 0:
            decay = min(1.0, (elapsed - min_time) / speed_window)
        else:
            decay = 0.0
        speed_pts = round(_MAX_POINTS - (_MAX_POINTS - _MIN_POINTS) * decay)
        pts = round(speed_pts * ratio)
        if pts > 0:
            new_scores[pid] = new_scores.get(pid, 0) + pts

    state.scores = new_scores
    state.poll_correct_ids = list(correct_set)
    await broadcast_state()

    for pid, ws in list(state.participants.items()):
        if pid == "__host__":
            continue
        selection = state.votes.get(pid)
        if selection is None:
            continue
        voted = set(selection) if isinstance(selection, list) else {selection}
        await ws.send_text(json.dumps({
            "type": "result",
            "correct_ids": list(correct_set),
            "voted_ids": list(voted),
            "score": state.scores.get(pid, 0),
        }))

    return {"ok": True}


@router.post("/api/poll/timer", dependencies=[Depends(require_host_auth)])
async def start_poll_timer(body: PollTimer):
    """Host starts a countdown; broadcasts timer to all clients."""
    if not state.poll_active:
        raise HTTPException(400, "Poll is not open")
    if not (1 <= body.seconds <= 120):
        raise HTTPException(400, "seconds must be 1–120")
    started_at = datetime.now(timezone.utc)
    state.poll_timer_seconds = body.seconds
    state.poll_timer_started_at = started_at
    await broadcast({"type": "timer", "seconds": body.seconds, "started_at": started_at.isoformat()})
    return {"ok": True}


@router.delete("/api/poll", dependencies=[Depends(require_host_auth)])
async def clear_poll():
    state.poll = None
    state.poll_active = False
    state.votes = {}
    state.poll_correct_ids = None
    state.base_scores = dict(state.scores)
    state.vote_times = {}
    state.current_activity = ActivityType.NONE
    await broadcast_state()
    return {"ok": True}


@router.get("/api/suggest-name")
async def suggest_name():
    return {"name": state.suggest_name()}


@router.get("/api/status")
async def status():
    return {
        "backend_version": get_backend_version(),
        "participants": len(participant_ids()),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "total_votes": len(state.votes),
        "needs_restore": state.needs_restore,
    }


@router.post("/api/pending-deploy")
async def set_pending_deploy(payload: dict):
    """Called by deploy watcher when a new push is detected on master."""
    state.pending_deploy = payload if payload.get("sha") else None
    await broadcast_state()
    return {"status": "ok"}
