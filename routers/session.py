"""Session stack management — host commands + daemon sync."""

import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_host_auth
from state import state
from messaging import broadcast_state

router = APIRouter()


def _get_sessions_root() -> Path | None:
    """Resolve the sessions root directory from env, same as quiz_core.find_session_folder."""
    sessions_root_str = os.environ.get(
        "SESSIONS_FOLDER",
        str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
    )
    p = Path(sessions_root_str).expanduser()
    return p if p.exists() and p.is_dir() else None


class StartSessionRequest(BaseModel):
    name: str


class RenameSessionRequest(BaseModel):
    name: str


class SyncSessionRequest(BaseModel):
    main: dict | None = None
    talk: dict | None = None
    discussion_points: list = []
    session_state: dict | None = None
    action: str | None = None
    # backward compat:
    stack: list | None = None
    key_points: list | None = None


@router.post("/api/session/start", dependencies=[Depends(require_host_auth)])
async def start_session(body: StartSessionRequest):
    state.session_request = {"action": "start", "name": body.name}
    return {"ok": True}


@router.post("/api/session/end", dependencies=[Depends(require_host_auth)])
async def end_session():
    state.session_request = {"action": "end"}
    return {"ok": True}


@router.post("/api/session/pause", dependencies=[Depends(require_host_auth)])
async def pause_session():
    state.session_request = {"action": "pause"}
    return {"ok": True}


@router.post("/api/session/resume", dependencies=[Depends(require_host_auth)])
async def resume_session():
    state.session_request = {"action": "resume"}
    return {"ok": True}


@router.patch("/api/session/rename", dependencies=[Depends(require_host_auth)])
async def rename_session(body: RenameSessionRequest):
    state.session_request = {"action": "rename", "name": body.name}
    return {"ok": True}


@router.get("/api/session/request", dependencies=[Depends(require_host_auth)])
async def poll_session_request():
    req = state.session_request
    state.session_request = None
    if req:
        return req
    return {"action": None}


@router.post("/api/session/sync", dependencies=[Depends(require_host_auth)])
async def sync_session(body: SyncSessionRequest):
    if body.main is not None or body.talk is not None:
        state.session_main = body.main
        state.session_talk = body.talk
    key_points = body.key_points or body.discussion_points
    if key_points:
        state.summary_points = key_points
        state.summary_updated_at = datetime.now()
    await broadcast_state()
    return {"ok": True}


@router.get("/api/session/folders", dependencies=[Depends(require_host_auth)])
async def list_session_folders():
    root = _get_sessions_root()
    folders = []
    if root:
        folders = sorted([f.name for f in root.iterdir() if f.is_dir()], reverse=True)
    return {"folders": folders}
