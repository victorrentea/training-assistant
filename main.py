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
from core.session_guard import require_valid_session, InvalidSessionRedirect
from core.state import state  # re-exported for test_main.py: from main import app, state
import core.metrics as metrics  # noqa: registers custom Prometheus metrics

from features.ws import router as ws
from features.ws.router import session_router as ws_session_router
from features.qa import router as qa
from features.wordcloud import router as wordcloud
from features.quiz import router as quiz
from features.summary import router as summary
from features.pages.router import landing_router, host_router, participant_router
from features.session import router as session
from features.session.router import session_router as session_session_router
from features.snapshot import router as snapshot
from features.slides import router as slides
from features.slides.upload import router as slides_upload_router
from features.transcription_language import router as transcription_language_router
from features.upload import router as upload
from features.upload.router import public_router as upload_public_router
from features.feedback import router as feedback
from features.internal.router import router as internal_router
from features.ws.proxy_bridge import participant_proxy_router

import core.state_builder  # noqa: registers core state builder
import features.qa.state_builder  # noqa
import features.wordcloud.state_builder  # noqa
import features.slides.state_builder  # noqa

logging.basicConfig(level=logging.INFO)


def _stamp_version_js():
    """Generate static/version.js with the current Bucharest timestamp at startup."""
    ts = datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d %H:%M")
    version_js = Path(__file__).parent / "static" / "version.js"
    version_js.write_text(f"window.APP_VERSION = '{ts}';\n", encoding="utf-8")
    logging.getLogger(__name__).info("version.js stamped: %s", ts)


def _stamp_deploy_info():
    """Generate static/deploy-info.json from Railway env vars at startup (no git needed)."""
    import json, os
    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")
    if not sha:
        return  # local dev — skip, file may be stale or absent
    msg = os.environ.get("RAILWAY_GIT_COMMIT_MESSAGE", "")
    ts = datetime.now(ZoneInfo("Europe/Bucharest")).isoformat()
    deploy_info = {
        "sha": sha[:8],
        "timestamp": datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d %H:%M"),
        "changelog": [msg] if msg else [],
        "commits": [{"sha": sha[:8], "msg": msg, "ts": ts}] if msg else [],
        "branches": [],
    }
    path = Path(__file__).parent / "static" / "deploy-info.json"
    path.write_text(json.dumps(deploy_info, indent=2), encoding="utf-8")
    logging.getLogger(__name__).info("deploy-info.json stamped: %s", sha[:8])


@asynccontextmanager
async def lifespan(app_: FastAPI):
    _stamp_version_js()
    _stamp_deploy_info()
    from features.slides.cache import seed_catalog_from_file
    seed_catalog_from_file()
    from features.ws.router import snapshot_pusher
    task = asyncio.create_task(snapshot_pusher())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Workshop Tool", lifespan=lifespan)


@app.exception_handler(InvalidSessionRedirect)
async def _redirect_invalid_session(request: Request, exc: InvalidSessionRedirect):
    from fastapi.responses import RedirectResponse
    from core.state import state as _state
    if _state.session_id:
        return RedirectResponse(f"/{_state.session_id}")
    return RedirectResponse("/?error=invalid")


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

# Global session lifecycle endpoints (no session prefix — host creates/ends sessions from here)
app.include_router(session.router)

# Daemon-facing slides upload endpoints (global — daemon doesn't know session_id)
app.include_router(slides_upload_router, dependencies=[Depends(require_host_auth)])

# Global transcription language endpoint
app.include_router(transcription_language_router, dependencies=[Depends(require_host_auth)])

# Global feedback endpoint
app.include_router(feedback.router)

# Internal daemon → backend file management endpoints
app.include_router(internal_router)


# ── Session-scoped host dependency ──

async def _require_active_session_host(session_id: str):
    """Validates that the session_id in the path matches the active session."""
    if not state.session_id or session_id.lower() != state.session_id.lower():
        raise HTTPException(status_code=404, detail="Session not found or not active")


# ── Session-scoped mode + screen-share ──

class ModeRequest(BaseModel):
    mode: str


# ── Session-scoped host router (/api/{session_id}/...) ──

session_host = APIRouter(
    prefix="/api/{session_id}",
    dependencies=[Depends(require_host_auth), Depends(_require_active_session_host)],
)
session_host.include_router(qa.router)
session_host.include_router(wordcloud.router)
session_host.include_router(quiz.router)
session_host.include_router(summary.router)
session_host.include_router(slides.router)
session_host.include_router(snapshot.router)
session_host.include_router(upload.router)
session_host.include_router(session_session_router)


@session_host.post("/screen-share")
async def toggle_screen_share():
    state.screen_share_active = not state.screen_share_active
    await broadcast_state()
    return {"screen_share_active": state.screen_share_active}


@session_host.post("/mode")
async def set_mode(req: ModeRequest):
    if req.mode not in ("workshop", "conference"):
        raise HTTPException(400, "mode must be 'workshop' or 'conference'")
    state.mode = req.mode
    await broadcast_state()
    return {"mode": state.mode}


app.include_router(session_host)

# ── Session-scoped participant routes (registered LAST — /{session_id} is a catch-all) ──

session_participant = APIRouter(
    prefix="/{session_id}",
    dependencies=[Depends(require_valid_session)],
)
session_participant.include_router(participant_router)       # /, /notes, /quiz
session_participant.include_router(slides.public_router)     # /api/slides, /api/slides/file/{slug}, /api/slides/current
session_participant.include_router(summary.public_router)    # /api/summary, /api/notes, /api/summary/force
session_participant.include_router(upload_public_router)     # /api/upload (participant file upload)
session_participant.include_router(participant_proxy_router)  # /api/participant/* → daemon proxy
app.include_router(session_participant)

app.mount("/static", StaticFiles(directory="static"), name="static")
