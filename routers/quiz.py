from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from messaging import broadcast
from state import state

router = APIRouter()


class QuizRequest(BaseModel):
    minutes: int = 30


class QuizStatus(BaseModel):
    status: str
    message: str = ""


class QuizPreview(BaseModel):
    question: str
    options: list[str]
    multi: bool = False
    correct_indices: list[int] = []


class QuizRefineRequest(BaseModel):
    target: str  # "question" | "opt0" | "opt1" | ...


@router.post("/api/quiz-request")
async def request_quiz(body: QuizRequest):
    state.quiz_request = {"minutes": body.minutes}
    state.quiz_status = {"status": "requested", "message": f"Waiting for daemon (last {body.minutes} min)…"}
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}


@router.get("/api/quiz-request")
async def poll_quiz_request():
    state.daemon_last_seen = datetime.now(timezone.utc)
    req = state.quiz_request
    state.quiz_request = None
    return {"request": req}


@router.post("/api/quiz-status")
async def update_quiz_status(body: QuizStatus):
    state.quiz_status = {"status": body.status, "message": body.message}
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
