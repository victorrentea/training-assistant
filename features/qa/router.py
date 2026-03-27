from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state

router = APIRouter()

_MAX_QUESTION_LENGTH = 280


class QuestionEdit(BaseModel):
    text: str


class AnswerToggle(BaseModel):
    answered: bool


@router.put("/api/qa/question/{question_id}/text", dependencies=[Depends(require_host_auth)])
async def edit_question(question_id: str, body: QuestionEdit):
    q = state.qa_questions.get(question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Question cannot be empty")
    if len(text) > _MAX_QUESTION_LENGTH:
        raise HTTPException(400, f"Question too long (max {_MAX_QUESTION_LENGTH} chars)")
    q["text"] = text
    await broadcast_state()
    return {"ok": True}


@router.delete("/api/qa/question/{question_id}", dependencies=[Depends(require_host_auth)])
async def delete_question(question_id: str):
    if question_id not in state.qa_questions:
        raise HTTPException(404, "Question not found")
    del state.qa_questions[question_id]
    await broadcast_state()
    return {"ok": True}


@router.put("/api/qa/question/{question_id}/answered", dependencies=[Depends(require_host_auth)])
async def toggle_answered(question_id: str, body: AnswerToggle):
    q = state.qa_questions.get(question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    q["answered"] = body.answered
    await broadcast_state()
    return {"ok": True}


@router.post("/api/qa/clear", dependencies=[Depends(require_host_auth)])
async def clear_qa():
    state.qa_questions = {}
    await broadcast_state()
    return {"ok": True}
