import asyncio
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state, ActivityType

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_LINES = 50
_CONFIRM_LINE_POINTS = 200


class CodeReviewCreate(BaseModel):
    snippet: str
    language: str | None = None
    smart_paste: bool = True


_EXTRACT_PROMPT = """Extract only the code snippet from the following text.
Remove any markdown formatting, explanations, comments about the code, or surrounding text.
Return ONLY a JSON object with two fields:
- "code": the extracted code (preserve original indentation, no markdown fences)
- "language": the programming language as lowercase identifier (one of: java, python, javascript, typescript, sql, go, csharp, kotlin, bash, or null if unknown)

If the input is already clean code with no surrounding text, return it as-is in the JSON format."""

_SMART_PASTE_INPUT_LIMIT = 10000


def _extract_code_with_ai(raw_snippet: str) -> tuple[str, str | None] | None:
    """Call Claude Haiku to extract code from LLM output.
    Returns (code, language) or None on any failure."""
    try:
        from daemon.llm.adapter import create_message
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None

        truncated = raw_snippet[:_SMART_PASTE_INPUT_LIMIT]
        response = create_message(
            api_key=api_key,
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": f"{_EXTRACT_PROMPT}\n\n---\n\n{truncated}"}],
            timeout=5.0,
        )

        text = response.content[0].text.strip()
        # Strip markdown fences if Claude wrapped the JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:text.rfind("```")]
        text = text.strip()

        result = json.loads(text)
        code = result.get("code", "").strip()
        if not code:
            return None
        language = result.get("language")
        if isinstance(language, str):
            language = language.lower()
        logger.info("Smart paste extracted %d lines, language=%s", len(code.splitlines()), language)
        return (code, language)
    except Exception:
        logger.debug("Smart paste extraction failed", exc_info=True)
        return None


class CodeReviewStatus(BaseModel):
    open: bool


class CodeReviewConfirmLine(BaseModel):
    line: int


@router.post("/api/codereview", dependencies=[Depends(require_host_auth)])
async def create_codereview(body: CodeReviewCreate):
    snippet = body.snippet.strip()
    if not snippet:
        raise HTTPException(400, "Snippet cannot be empty")

    detected_language = None
    if body.smart_paste:
        result = await asyncio.to_thread(_extract_code_with_ai, snippet)
        if result:
            snippet, detected_language = result

    lines = snippet.splitlines()
    if len(lines) > _MAX_LINES:
        raise HTTPException(400, f"Snippet cannot exceed {_MAX_LINES} lines")
    if state.current_activity not in (ActivityType.NONE, ActivityType.CODEREVIEW):
        raise HTTPException(409, "Another activity is already active")

    state.codereview_snippet = snippet
    # Use detected language only if host chose "Auto-detect" (null)
    state.codereview_language = body.language if body.language is not None else detected_language
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
