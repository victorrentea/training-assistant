"""Daemon code review router — participant + host endpoints."""
import asyncio
import json
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.codereview.state import codereview_state
from daemon.participant.state import participant_state
from daemon.scores import scores

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None


def set_ws_client(client):
    """Set the WebSocket client for broadcasting events."""
    global _ws_client
    _ws_client = client


# ── Smart paste logic (copied from features/codereview/router.py) ──

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


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/codereview", tags=["codereview"])


@participant_router.put("/selection")
async def update_selection(request: Request):
    """Participant sets their selected lines (full replacement)."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "codereview":
        return JSONResponse({"error": "Code review not active"}, status_code=409)

    # Phase gate
    if codereview_state.phase != "selecting":
        return JSONResponse({"error": "Selection phase is closed"}, status_code=409)

    body = await request.json()
    lines = body.get("lines", [])
    if not isinstance(lines, list):
        return JSONResponse({"error": "lines must be a list"}, status_code=400)

    codereview_state.select_lines(pid, lines)

    # Broadcast selection update (line counts for host)
    line_counts = {
        str(ln): sum(1 for sel in codereview_state.selections.values() if ln in sel)
        for pid_sel in codereview_state.selections.values()
        for ln in pid_sel
    }
    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "codereview_selections_updated", "line_counts": line_counts}},
    ]

    return JSONResponse({"ok": True})


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/codereview') which expands to /api/{session_id}/codereview.
# The prefix includes {session_id} path parameter to match this pattern.

host_router = APIRouter(prefix="/api/{session_id}/codereview", tags=["codereview"])

_MAX_LINES = 50


@host_router.post("")
async def create_codereview(request: Request):
    """Host creates a code review session."""
    body = await request.json()
    snippet = str(body.get("snippet", "")).strip()
    language = body.get("language")  # None means auto-detect
    smart_paste = body.get("smart_paste", True)

    if not snippet:
        return JSONResponse({"error": "Snippet cannot be empty"}, status_code=400)

    detected_language = None
    if smart_paste:
        result = await asyncio.to_thread(_extract_code_with_ai, snippet)
        if result:
            snippet, detected_language = result

    lines = snippet.splitlines()
    if len(lines) > _MAX_LINES:
        return JSONResponse({"error": f"Snippet cannot exceed {_MAX_LINES} lines"}, status_code=400)

    # Use detected language only if host chose "Auto-detect" (null)
    final_language = language if language is not None else detected_language

    participant_state.current_activity = "codereview"
    codereview_state.create(snippet, final_language)

    _broadcast({"type": "codereview_opened", "snippet": snippet, "language": final_language})
    _broadcast({"type": "activity_updated", "current_activity": "codereview"})

    return JSONResponse({"ok": True})


@host_router.put("/status")
async def set_codereview_status(request: Request):
    """Host closes the selection phase."""
    body = await request.json()
    is_open = body.get("open", True)

    if not is_open:
        codereview_state.close_selection()
        _broadcast({"type": "codereview_selection_closed"})

    return JSONResponse({"ok": True, "phase": codereview_state.phase})


@host_router.put("/confirm-line")
async def confirm_line(request: Request):
    """Host confirms a line as problematic and awards points."""
    if not codereview_state.snippet:
        return JSONResponse({"error": "No code review created yet"}, status_code=400)

    body = await request.json()
    line = body.get("line")
    if line is None:
        return JSONResponse({"error": "Missing line"}, status_code=400)

    line_count = len(codereview_state.snippet.splitlines())
    if line < 0 or line >= line_count:
        return JSONResponse({"error": f"Line {line} is out of range (0–{line_count - 1})"}, status_code=400)

    if line in codereview_state.confirmed:
        return JSONResponse({"error": f"Line {line} is already confirmed"}, status_code=409)

    awarded_pids = codereview_state.confirm_line(line)

    for pid in awarded_pids:
        scores.add_score(pid, 200)

    _broadcast({"type": "codereview_line_confirmed", "line": line})
    _broadcast({"type": "scores_updated", "scores": scores.snapshot()})

    return JSONResponse({"ok": True, "confirmed_line": line})


@host_router.delete("")
async def clear_codereview(request: Request):
    """Host clears the code review."""
    codereview_state.clear()
    participant_state.current_activity = "none"

    _broadcast({"type": "codereview_cleared"})
    _broadcast({"type": "activity_updated", "current_activity": "none"})

    return JSONResponse({"ok": True})


def _broadcast(event: dict):
    """Send broadcast directly via ws_client (host-direct path)."""
    if _ws_client is None:
        return
    _ws_client.send({"type": "broadcast", "event": event})
