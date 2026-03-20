import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast_state
from state import state, ActivityType

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_LINES = 50
_CONFIRM_LINE_POINTS = 200


class CodeReviewCreate(BaseModel):
    snippet: str
    language: str | None = None


class CodeReviewStatus(BaseModel):
    open: bool


class CodeReviewConfirmLine(BaseModel):
    line: int


@router.post("/api/codereview", dependencies=[Depends(require_host_auth)])
async def create_codereview(body: CodeReviewCreate):
    snippet = body.snippet.strip()
    if not snippet:
        raise HTTPException(400, "Snippet cannot be empty")
    lines = snippet.splitlines()
    if len(lines) > _MAX_LINES:
        raise HTTPException(400, f"Snippet cannot exceed {_MAX_LINES} lines")
    if state.current_activity not in (ActivityType.NONE, ActivityType.CODEREVIEW):
        raise HTTPException(409, "Another activity is already active")

    state.codereview_snippet = snippet
    state.codereview_language = body.language
    state.codereview_phase = "selecting"
    state.codereview_selections = {}
    state.codereview_confirmed = set()
    state.current_activity = ActivityType.CODEREVIEW

    await broadcast_state()
    return {"ok": True}


@router.put("/api/codereview/status", dependencies=[Depends(require_host_auth)])
async def set_codereview_status(body: CodeReviewStatus):
    if not state.codereview_snippet:
        raise HTTPException(400, "No code review created yet")
    if not body.open:
        state.codereview_phase = "reviewing"
        await broadcast_state()
    # open=True is a no-op
    return {"ok": True, "phase": state.codereview_phase}


@router.put("/api/codereview/confirm-line", dependencies=[Depends(require_host_auth)])
async def confirm_line(body: CodeReviewConfirmLine):
    if not state.codereview_snippet:
        raise HTTPException(400, "No code review created yet")
    line_count = len(state.codereview_snippet.splitlines())
    if body.line < 0 or body.line >= line_count:
        raise HTTPException(400, f"Line {body.line} is out of range (0–{line_count - 1})")
    if body.line in state.codereview_confirmed:
        raise HTTPException(409, f"Line {body.line} is already confirmed")

    state.codereview_confirmed.add(body.line)

    # Award points to every participant who selected this line
    for pid, selected_lines in state.codereview_selections.items():
        if body.line in selected_lines:
            state.scores[pid] = state.scores.get(pid, 0) + _CONFIRM_LINE_POINTS

    await broadcast_state()
    return {"ok": True, "confirmed_line": body.line}


@router.delete("/api/codereview", dependencies=[Depends(require_host_auth)])
async def clear_codereview():
    state.codereview_snippet = None
    state.codereview_language = None
    state.codereview_phase = "idle"
    state.codereview_selections = {}
    state.codereview_confirmed = set()
    state.current_activity = ActivityType.NONE

    await broadcast_state()
    return {"ok": True}
