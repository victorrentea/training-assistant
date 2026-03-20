"""
Workshop Live Interaction Tool
FastAPI + WebSocket backend
"""

import logging

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles

from auth import require_host_auth
from state import state  # re-exported for test_main.py: from main import app, state
from routers import ws, poll, scores, quiz, pages, wordcloud, activity, qa, codereview, summary

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Workshop Tool")

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

app.mount("/static", StaticFiles(directory="static"), name="static")
