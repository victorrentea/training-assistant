import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast, build_state_message
from state import state

router = APIRouter()

_MAX_QUESTION_LENGTH = 280


class QuestionSubmit(BaseModel):
    name: str
    text: str


class QuestionUpvote(BaseModel):
    name: str
    question_id: str


class QuestionEdit(BaseModel):
    text: str


class AnswerToggle(BaseModel):
    answered: bool


@router.post("/api/qa/question")
async def submit_question(body: QuestionSubmit):
    text = body.text.strip()
    name = body.name.strip()
    if not text:
        raise HTTPException(400, "Question cannot be empty")
    if len(text) > _MAX_QUESTION_LENGTH:
        raise HTTPException(400, f"Question too long (max {_MAX_QUESTION_LENGTH} chars)")
    if not name:
        raise HTTPException(400, "Name is required")

    qid = str(uuid.uuid4())
    state.qa_questions[qid] = {
        "id": qid,
        "text": text,
        "author": name,
        "upvoters": set(),
        "answered": False,
        "timestamp": time.time(),
    }
    # Award +100 points to author
    state.scores[name] = state.scores.get(name, 0) + 100
    await broadcast(build_state_message())
    return {"ok": True, "id": qid}


@router.post("/api/qa/upvote")
async def upvote_question(body: QuestionUpvote):
    name = body.name.strip()
    q = state.qa_questions.get(body.question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    if q["author"] == name:
        raise HTTPException(400, "Cannot upvote your own question")
    if name in q["upvoters"]:
        raise HTTPException(400, "Already upvoted")

    q["upvoters"].add(name)
    # Award +50 points to the question author
    author = q["author"]
    state.scores[author] = state.scores.get(author, 0) + 50
    # Award +25 points to the upvoter
    state.scores[name] = state.scores.get(name, 0) + 25
    await broadcast(build_state_message())
    return {"ok": True}


@router.patch("/api/qa/question/{question_id}", dependencies=[Depends(require_host_auth)])
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
    await broadcast(build_state_message())
    return {"ok": True}


@router.delete("/api/qa/question/{question_id}", dependencies=[Depends(require_host_auth)])
async def delete_question(question_id: str):
    if question_id not in state.qa_questions:
        raise HTTPException(404, "Question not found")
    del state.qa_questions[question_id]
    await broadcast(build_state_message())
    return {"ok": True}


@router.post("/api/qa/answer/{question_id}", dependencies=[Depends(require_host_auth)])
async def toggle_answered(question_id: str, body: AnswerToggle):
    q = state.qa_questions.get(question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    q["answered"] = body.answered
    await broadcast(build_state_message())
    return {"ok": True}


@router.post("/api/qa/clear", dependencies=[Depends(require_host_auth)])
async def clear_qa():
    state.qa_questions = {}
    await broadcast(build_state_message())
    return {"ok": True}
