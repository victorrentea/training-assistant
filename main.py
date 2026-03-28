"""
Workshop Live Interaction Tool
FastAPI + WebSocket backend
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.session_guard import require_valid_session
from core.state import state  # re-exported for test_main.py: from main import app, state
import core.metrics as metrics  # noqa: registers custom Prometheus metrics

from features.ws import router as ws
from features.ws.router import session_router as ws_session_router
from features.poll import router as poll
from features.poll.router import public_router as poll_public_router
from features.qa import router as qa
from features.wordcloud import router as wordcloud
from features.codereview import router as codereview
from features.debate import router as debate
from features.quiz import router as quiz
from features.summary import router as summary
from features.leaderboard import router as leaderboard
from features.activity import router as activity
from features.pages.router import landing_router, host_router, participant_router
from features.session import router as session
from features.snapshot import router as snapshot
from features.slides import router as slides
from features.transcription_language import router as transcription_language_router
from features.upload import router as upload
from features.upload.router import public_router as upload_public_router
from features.feedback import router as feedback

import core.state_builder  # noqa: registers core state builder
import features.poll.state_builder  # noqa
import features.qa.state_builder  # noqa
import features.wordcloud.state_builder  # noqa
import features.codereview.state_builder  # noqa
import features.debate.state_builder  # noqa
import features.leaderboard.state_builder  # noqa
import features.slides.state_builder  # noqa

logging.basicConfig(level=logging.INFO)


def _stamp_version_js():
    """Generate static/version.js with the current Bucharest timestamp at startup."""
    ts = datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d %H:%M")
    version_js = Path(__file__).parent / "static" / "version.js"
    version_js.write_text(f"window.APP_VERSION = '{ts}';\n", encoding="utf-8")
    logging.getLogger(__name__).info("version.js stamped: %s", ts)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    _stamp_version_js()
    from features.slides.cache import seed_catalog_from_file
    seed_catalog_from_file()
    yield


app = FastAPI(title="Workshop Tool", lifespan=lifespan)


@app.middleware("http")
async def add_avatar_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/avatars/") and path.endswith(".png"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", dependencies=[Depends(require_host_auth)]
)

# ── Root-level routes (registered FIRST to prevent /{session_id} catch-all conflicts) ──

# WebSocket: daemon + host/overlay (no session prefix)
app.include_router(ws.router)
# WebSocket: session-scoped participant connections
app.include_router(ws_session_router)

# Pages: landing at /, host at /host (auth-protected)
app.include_router(landing_router)
app.include_router(host_router)

# Host-auth API routes (no session prefix — host/daemon use these directly)
app.include_router(poll.router)
app.include_router(quiz.router, dependencies=[Depends(require_host_auth)])
app.include_router(wordcloud.router)
app.include_router(activity.router)
app.include_router(qa.router)
app.include_router(codereview.router)
app.include_router(summary.router, dependencies=[Depends(require_host_auth)])
app.include_router(slides.router, dependencies=[Depends(require_host_auth)])
app.include_router(debate.router)
app.include_router(leaderboard.router)
app.include_router(session.router)
app.include_router(snapshot.router, dependencies=[Depends(require_host_auth)])
app.include_router(transcription_language_router, dependencies=[Depends(require_host_auth)])
app.include_router(upload.router)  # host download endpoint (GET /api/upload/{id})
app.include_router(feedback.router)

# ── Session-scoped participant routes (registered LAST — /{session_id} is a catch-all) ──

session_participant = APIRouter(
    prefix="/{session_id}",
    dependencies=[Depends(require_valid_session)],
)
session_participant.include_router(participant_router)       # /, /notes, /quiz
session_participant.include_router(poll_public_router)       # /api/suggest-name, /api/status, /api/quiz-md
session_participant.include_router(slides.public_router)     # /api/slides, /api/slides/file/{slug}, /api/slides/current
session_participant.include_router(summary.public_router)    # /api/summary, /api/notes, /api/summary/force
session_participant.include_router(upload_public_router)     # /api/upload (participant file upload)
app.include_router(session_participant)

class ModeRequest(BaseModel):
    mode: str

@app.post("/api/screen-share", dependencies=[Depends(require_host_auth)])
async def toggle_screen_share():
    state.screen_share_active = not state.screen_share_active
    await broadcast_state()
    return {"screen_share_active": state.screen_share_active}


@app.post("/api/mode", dependencies=[Depends(require_host_auth)])
async def set_mode(req: ModeRequest):
    if req.mode not in ("workshop", "conference"):
        raise HTTPException(400, "mode must be 'workshop' or 'conference'")
    state.mode = req.mode
    if req.mode == "conference" and state.session_talk is None:
        state.session_request = {"action": "create_talk_folder"}
    await broadcast_state()
    return {"mode": state.mode}

app.mount("/static", StaticFiles(directory="static"), name="static")
