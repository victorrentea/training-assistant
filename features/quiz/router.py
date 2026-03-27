from datetime import datetime, timezone
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from core.messaging import broadcast
from quiz_core import DEFAULT_TRANSCRIPT_MINUTES
from core.state import state

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


class SlideStatus(BaseModel):
    name: str
    url: str
    slug: str | None = None
    updated_at: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    sync_status: str | None = None
    sync_message: str | None = None


class QuizStatus(BaseModel):
    status: str
    message: str = ""
    session_folder: str | None = None
    session_notes: str | None = None
    slides: list[SlideStatus] | None = None


class QuizPreview(BaseModel):
    question: str
    options: list[str]
    multi: bool = False
    correct_indices: list[int] = []
    source: str | None = None
    page: str | None = None


class QuizRefineRequest(BaseModel):
    target: str  # "question" | "opt0" | "opt1" | ...

_SLUG_SANITIZER = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    raw = value.strip().lower()
    raw = _SLUG_SANITIZER.sub("-", raw).strip("-")
    return raw or "slide"


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
        "has_key_points": len(state.summary_points) > 0,
        "has_slides": len(state.slides) > 0,
        "needs_restore": state.needs_restore,
    }


@router.post("/api/quiz-status")
async def update_quiz_status(body: QuizStatus):
    state.quiz_status = {"status": body.status, "message": body.message}
    if body.session_folder is not None or body.session_notes is not None:
        state.daemon_session_folder = body.session_folder
        state.daemon_session_notes = body.session_notes
    if body.slides is not None:
        normalized: list[dict] = []
        seen: set[str] = set()
        for idx, slide in enumerate(body.slides):
            name = (slide.name or "").strip()
            url = (slide.url or "").strip()
            if not name or not url:
                continue
            slug = (slide.slug or "").strip() or _slugify(name)
            if slug in seen:
                slug = f"{slug}-{idx+1}"
            seen.add(slug)
            normalized.append({
                "name": name,
                "slug": slug,
                "url": url,
                "updated_at": slide.updated_at,
                "etag": slide.etag,
                "last_modified": slide.last_modified,
                "sync_status": slide.sync_status,
                "sync_message": slide.sync_message,
            })
        state.slides = normalized
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}


@router.post("/api/quiz-preview")
async def set_quiz_preview(body: QuizPreview):
    state.quiz_preview = {
        "question": body.question,
        "options": body.options,
        "multi": body.multi,
        "correct_indices": body.correct_indices,
        "source": body.source,
        "page": body.page,
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
