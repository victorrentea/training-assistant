from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from messaging import broadcast
from quiz_core import DEFAULT_TRANSCRIPT_MINUTES
from state import state

router = APIRouter()


class QuizRequest(BaseModel):
    minutes: int | None = None   # transcript mode
    topic: str | None = None     # topic mode

    @model_validator(mode="after")
    def exactly_one_mode(self):
        has_minutes = self.minutes is not None and self.minutes > 0
        has_topic = bool(self.topic and self.topic.strip())
        if has_minutes == has_topic:
            raise ValueError("Provide either 'minutes' (transcript mode) or 'topic' (topic mode), not both or neither.")
        return self


class QuizStatus(BaseModel):
    status: str
    message: str = ""
    session_folder: str | None = None
    session_notes: str | None = None


class QuizPreview(BaseModel):
    question: str
    options: list[str]
    multi: bool = False
    correct_indices: list[int] = []


class QuizRefineRequest(BaseModel):
    target: str  # "question" | "opt0" | "opt1" | ...


@router.post("/api/quiz-request")
async def request_quiz(body: QuizRequest):
    if body.topic:
        state.quiz_request = {"minutes": None, "topic": body.topic}
        msg = f"Waiting for daemon (topic: {body.topic})…"
    else:
        minutes = body.minutes or DEFAULT_TRANSCRIPT_MINUTES
        state.quiz_request = {"minutes": minutes, "topic": None}
        msg = f"Waiting for daemon (last {minutes} min)…"
    state.quiz_status = {"status": "requested", "message": msg}
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}


@router.get("/api/quiz-request")
async def poll_quiz_request():
    state.daemon_last_seen = datetime.now(timezone.utc)
    req = state.quiz_request
    state.quiz_request = None
    return {
        "request": req,
        "session_folder": state.daemon_session_folder,
        "has_notes_content": state.notes_content is not None,
    }


@router.post("/api/quiz-status")
async def update_quiz_status(body: QuizStatus):
    state.quiz_status = {"status": body.status, "message": body.message}
    if body.session_folder is not None or body.session_notes is not None:
        state.daemon_session_folder = body.session_folder
        state.daemon_session_notes = body.session_notes
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}


@router.post("/api/quiz-preview")
async def set_quiz_preview(body: QuizPreview):
    state.quiz_preview = {
        "question": body.question,
        "options": body.options,
        "multi": body.multi,
        "correct_indices": body.correct_indices,
    }
    await broadcast({"type": "quiz_preview", "quiz": state.quiz_preview})
    return {"ok": True}


@router.delete("/api/quiz-preview")
async def clear_quiz_preview():
    state.quiz_preview = None
    await broadcast({"type": "quiz_preview", "quiz": None})
    return {"ok": True}


@router.post("/api/quiz-refine")
async def request_quiz_refine(body: QuizRefineRequest):
    if not state.quiz_preview:
        raise HTTPException(400, "No preview to refine")
    state.quiz_refine_request = {"target": body.target}
    state.quiz_status = {"status": "generating", "message": f"Regenerating {'question' if body.target == 'question' else 'option'}…"}
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}


@router.get("/api/quiz-refine")
async def poll_quiz_refine():
    state.daemon_last_seen = datetime.now(timezone.utc)
    req = state.quiz_refine_request
    state.quiz_refine_request = None
    return {"request": req, "preview": state.quiz_preview}
