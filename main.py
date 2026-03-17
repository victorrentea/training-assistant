"""
Workshop Live Interaction Tool
FastAPI + WebSocket backend
"""

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from state import state  # re-exported for test_main.py: from main import app, state
from routers import ws, poll, scores, quiz, pages

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Workshop Tool")

app.include_router(ws.router)
app.include_router(poll.router)
app.include_router(scores.router)
app.include_router(quiz.router)
app.include_router(pages.router)

app.mount("/static", StaticFiles(directory="static"), name="static")
