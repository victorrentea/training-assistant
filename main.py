"""
Workshop Live Interaction Tool
FastAPI + WebSocket backend
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state  # re-exported for test_main.py: from main import app, state
import core.metrics as metrics  # noqa: registers custom Prometheus metrics

from features.ws import router as ws
from features.poll import router as poll
from features.qa import router as qa
from features.wordcloud import router as wordcloud
from features.codereview import router as codereview
from features.debate import router as debate
from features.quiz import router as quiz
from features.summary import router as summary
from features.leaderboard import router as leaderboard
from features.activity import router as activity
from features.pages import router as pages
from features.session import router as session
from features.snapshot import router as snapshot
from features.slides import router as slides
from features.transcription_language import router as transcription_language_router
from features.upload import router as upload

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


_bg_logger = logging.getLogger("bg_poller")


async def _daemon_ping_loop():
    """Background task: send a server_ping to the daemon WS every 5 seconds."""
    while True:
        await asyncio.sleep(5)
        ws = state.daemon_ws
        if ws is not None:
            try:
                ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                await ws.send_json({"type": "server_ping", "ts": ts})
                _bg_logger.info("server_ping sent to daemon at %s", ts)
            except Exception as exc:
                _bg_logger.warning("server_ping failed: %s", exc)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    _stamp_version_js()
    task = asyncio.create_task(_daemon_ping_loop())
    try:
        yield
    finally:
        task.cancel()


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

app.include_router(ws.router)
app.include_router(poll.router)
app.include_router(quiz.router, dependencies=[Depends(require_host_auth)])
app.include_router(pages.router)
app.include_router(wordcloud.router)
app.include_router(activity.router)
app.include_router(qa.router)
app.include_router(codereview.router)
app.include_router(summary.router, dependencies=[Depends(require_host_auth)])
app.include_router(summary.public_router)
app.include_router(slides.router, dependencies=[Depends(require_host_auth)])
app.include_router(slides.public_router)
app.include_router(debate.router)
app.include_router(leaderboard.router)
app.include_router(session.router)
app.include_router(snapshot.router, dependencies=[Depends(require_host_auth)])
app.include_router(transcription_language_router, dependencies=[Depends(require_host_auth)])
app.include_router(upload.router)

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
