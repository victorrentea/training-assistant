"""Daemon Q&A router — participant + host endpoints."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.host_ws import send_to_host
from daemon.participant.state import participant_state
from daemon.qa.state import qa_state
from daemon.scores import scores

logger = logging.getLogger(__name__)

_ws_client = None


def set_ws_client(client):
    global _ws_client
    _ws_client = client


def _build_questions():
    """Helper: build question list with resolved names."""
    return qa_state.build_question_list(
        participant_state.participant_names,
        participant_state.participant_avatars,
    )


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/qa", tags=["qa"])


@participant_router.post("/submit")
async def submit_question(request: Request):
    """Participant submits a Q&A question."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    # No activity gate — Railway accepts Q&A submissions regardless of current activity

    qa_state.submit(pid, text)
    questions = _build_questions()

    scores.add_score(pid, 100)
    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "qa_updated", "questions": questions}},
        {"type": "broadcast", "event": {"type": "scores_updated", "scores": scores.snapshot()}},
    ]

    await send_to_host({"type": "qa_updated", "questions": questions})
    await send_to_host({"type": "scores_updated", "scores": scores.snapshot()})

    return JSONResponse({"ok": True})


@participant_router.post("/upvote")
async def upvote_question(request: Request):
    """Participant upvotes a Q&A question."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    question_id = str(body.get("question_id", ""))
    if not question_id:
        return JSONResponse({"error": "Missing question_id"}, status_code=400)

    success, author_pid = qa_state.upvote(question_id, pid)
    if not success:
        return JSONResponse({"error": "Cannot upvote"}, status_code=409)

    questions = _build_questions()

    scores.add_score(author_pid, 50)
    scores.add_score(pid, 25)
    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "qa_updated", "questions": questions}},
        {"type": "broadcast", "event": {"type": "scores_updated", "scores": scores.snapshot()}},
    ]

    await send_to_host({"type": "qa_updated", "questions": questions})
    await send_to_host({"type": "scores_updated", "scores": scores.snapshot()})

    return JSONResponse({"ok": True})


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/qa/submit') which expands to /api/{session_id}/qa/submit.

host_router = APIRouter(prefix="/api/{session_id}/qa", tags=["qa"])


@host_router.post("/submit")
async def host_submit_question(request: Request):
    """Host submits a Q&A question — no scoring."""
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    qa_state.submit("__host__", text)
    await _send_qa_events()
    return JSONResponse({"ok": True})


@host_router.put("/question/{question_id}/text")
async def edit_question_text(question_id: str, request: Request):
    """Host edits a question's text."""
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)
    if not qa_state.edit_text(question_id, text):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})


@host_router.delete("/question/{question_id}")
async def delete_question(question_id: str):
    """Host deletes a question."""
    if not qa_state.delete(question_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})


@host_router.put("/question/{question_id}/answered")
async def toggle_answered(question_id: str, request: Request):
    """Host toggles a question's answered flag."""
    body = await request.json()
    answered = bool(body.get("answered", False))
    if not qa_state.toggle_answered(question_id, answered):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})


@host_router.post("/clear")
async def clear_qa():
    """Host clears all Q&A questions."""
    qa_state.clear()
    await _send_qa_events()
    return JSONResponse({"ok": True})


async def _send_qa_events():
    """Send broadcast to participants (via Railway) and to host (local WS)."""
    questions = _build_questions()
    if _ws_client:
        _ws_client.send({
            "type": "broadcast",
            "event": {"type": "qa_updated", "questions": questions},
        })
    await send_to_host({"type": "qa_updated", "questions": questions})
