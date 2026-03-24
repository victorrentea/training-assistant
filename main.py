"""
Workshop Live Interaction Tool
FastAPI + WebSocket backend
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

from auth import require_host_auth
from messaging import broadcast_state
from state import state  # re-exported for test_main.py: from main import app, state
import metrics  # noqa: registers custom Prometheus metrics
from routers import ws, poll, scores, quiz, pages, wordcloud, activity, qa, codereview, summary, debate, leaderboard, session, state_snapshot

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
    yield


app = FastAPI(title="Workshop Tool", lifespan=lifespan)

Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", dependencies=[Depends(require_host_auth)]
)

app.include_router(ws.router)
app.include_router(poll.router)
app.include_router(scores.router)
app.include_router(quiz.router, dependencies=[Depends(require_host_auth)])
app.include_router(pages.router)
app.include_router(wordcloud.router)
app.include_router(activity.router)
app.include_router(qa.router)
app.include_router(codereview.router)
app.include_router(summary.router, dependencies=[Depends(require_host_auth)])
app.include_router(summary.public_router)
app.include_router(debate.router)
app.include_router(leaderboard.router)
app.include_router(session.router)
app.include_router(state_snapshot.router, dependencies=[Depends(require_host_auth)])

class ModeRequest(BaseModel):
    mode: str

@app.post("/api/mode", dependencies=[Depends(require_host_auth)])
async def set_mode(req: ModeRequest):
    if req.mode not in ("workshop", "conference"):
        raise HTTPException(400, "mode must be 'workshop' or 'conference'")
    state.mode = req.mode
    await broadcast_state()
    return {"mode": state.mode}

app.mount("/static", StaticFiles(directory="static"), name="static")
