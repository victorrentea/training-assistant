"""Daemon Q&A router — participant + host endpoints."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.participant.state import participant_state
from daemon.qa.state import qa_state
from daemon.scores import scores
from daemon.ws_messages import QaUpdatedMsg, ScoresUpdatedMsg
from daemon.ws_publish import broadcast_event, broadcast, notify_host

logger = logging.getLogger(__name__)


class OkResponse(BaseModel):
    ok: bool = True


class SubmitQuestionBody(BaseModel):
    text: str


class UpvoteQuestionBody(BaseModel):
    question_id: str


class EditQuestionTextBody(BaseModel):
    text: str


class ToggleAnsweredBody(BaseModel):
    answered: bool = False


def _build_questions_for_host():
    """Helper: build question list with resolved names for host."""
    return qa_state.build_question_list(
        participant_state.participant_names,
        participant_state.participant_avatars,
    )


def _build_questions_for_broadcast():
    """Helper: build raw question list for participant broadcast."""
    return qa_state.build_question_list_raw()


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/qa", tags=["qa"])


@participant_router.post("/submit")
async def submit_question(request: Request, body: SubmitQuestionBody):
    """Participant submits a Q&A question."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    text = body.text.strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    # No activity gate — Railway accepts Q&A submissions regardless of current activity

    qa_state.submit(pid, text)
    raw_questions = _build_questions_for_broadcast()
    host_questions = _build_questions_for_host()

    scores.add_score(pid, 100)
    request.state.write_back_events = [
        broadcast_event(QaUpdatedMsg(questions=raw_questions)),
        broadcast_event(ScoresUpdatedMsg(scores=scores.snapshot())),
    ]

    await notify_host(QaUpdatedMsg(questions=host_questions))
    await notify_host(ScoresUpdatedMsg(scores=scores.snapshot()))

    return OkResponse()


@participant_router.post("/upvote")
async def upvote_question(request: Request, body: UpvoteQuestionBody):
    """Participant upvotes a Q&A question."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    question_id = body.question_id
    if not question_id:
        return JSONResponse({"error": "Missing question_id"}, status_code=400)

    success, author_pid = qa_state.upvote(question_id, pid)
    if not success:
        return JSONResponse({"error": "Cannot upvote"}, status_code=409)

    raw_questions = _build_questions_for_broadcast()
    host_questions = _build_questions_for_host()

    scores.add_score(author_pid, 50)
    scores.add_score(pid, 25)
    request.state.write_back_events = [
        broadcast_event(QaUpdatedMsg(questions=raw_questions)),
        broadcast_event(ScoresUpdatedMsg(scores=scores.snapshot())),
    ]

    await notify_host(QaUpdatedMsg(questions=host_questions))
    await notify_host(ScoresUpdatedMsg(scores=scores.snapshot()))

    return OkResponse()


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/qa/submit') which expands to /api/{session_id}/qa/submit.

host_router = APIRouter(prefix="/api/{session_id}/host/qa", tags=["qa"])


@host_router.post("/submit")
async def host_submit_question(body: SubmitQuestionBody):
    """Host submits a Q&A question — no scoring."""
    text = body.text.strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    qa_state.submit("__host__", text)
    await _send_qa_events()
    return OkResponse()


@host_router.put("/question/{question_id}/text")
async def edit_question_text(question_id: str, body: EditQuestionTextBody):
    """Host edits a question's text."""
    text = body.text.strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)
    if not qa_state.edit_text(question_id, text):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return OkResponse()


@host_router.delete("/question/{question_id}")
async def delete_question(question_id: str):
    """Host deletes a question."""
    if not qa_state.delete(question_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return OkResponse()


@host_router.put("/question/{question_id}/answered")
async def toggle_answered(question_id: str, body: ToggleAnsweredBody):
    """Host toggles a question's answered flag."""
    if not qa_state.toggle_answered(question_id, body.answered):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return OkResponse()


@host_router.post("/clear")
async def clear_qa():
    """Host clears all Q&A questions."""
    qa_state.clear()
    await _send_qa_events()
    return OkResponse()


async def _send_qa_events():
    """Send broadcast to participants (via Railway) and to host (local WS)."""
    raw_questions = _build_questions_for_broadcast()
    host_questions = _build_questions_for_host()
    broadcast(QaUpdatedMsg(questions=raw_questions))
    await notify_host(QaUpdatedMsg(questions=host_questions))
