"""
Workshop Live Interaction Tool
FastAPI + WebSocket backend
"""

import logging

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

from auth import require_host_auth
from messaging import broadcast_state
from state import state  # re-exported for test_main.py: from main import app, state
import metrics  # noqa: registers custom Prometheus metrics
from routers import ws, poll, scores, quiz, pages, wordcloud, activity, qa, codereview, summary, debate

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Workshop Tool")

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
