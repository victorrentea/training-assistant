"""Session lifecycle endpoints — host-only, served directly by daemon localhost.

Migrated from features/session/router.py on Railway.
Instead of queuing requests for Railway to forward via WS, endpoints now
put requests directly into daemon/session/pending.py for the orchestrator loop.
"""
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.session import pending as session_pending
from daemon.session import state as session_state
from daemon.session_state import announce_session_id, load_session_meta


def normalize_session_name(name: str) -> str:
    """Replace non-breaking spaces and other Unicode whitespace with regular spaces."""
    return name.replace('\xa0', ' ').strip()


def _generate_session_id() -> str:
    """Generate a new 6-char alphanumeric session ID."""
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))


def _resolve_session_id_for_folder(folder_name: str) -> str:
    """Return stable session_id for a folder, loading from session-state.json or generating a new one."""
    root = _get_sessions_root()
    if root:
        folder = root / folder_name
        if folder.exists():
            meta = load_session_meta(folder)
            if meta.get("session_id"):
                return meta["session_id"]
    return _generate_session_id()

logger = logging.getLogger(__name__)

def set_ws_client(client) -> None:
    """No-op: ws_client no longer needed after session broadcast removal."""
    pass


def _get_sessions_root() -> Path | None:
    """Resolve sessions root from env or use the shared state."""
    root = session_state.get_sessions_root()
    if root is not None:
        return root
    # Fallback: read from env directly
    sessions_root_str = os.environ.get(
        "SESSIONS_FOLDER",
        str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
    )
    p = Path(sessions_root_str).expanduser()
    return p if p.exists() and p.is_dir() else None


def _filter_folders_to_current_year(folders: list[str], current_year: int | None = None) -> list[str]:
    year = current_year or datetime.now(timezone.utc).year
    year_prefix = str(year)
    return [name for name in folders if re.match(rf"^{re.escape(year_prefix)}(?!\d)", name)]


def _dedupe_normalized_folder_names(folders: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in folders:
        name = normalize_session_name(str(raw))
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


# ── Global host session endpoints (no session_id prefix) ──

global_router = APIRouter(prefix="/api/session", tags=["session"])
# Public endpoint needs a separate router without auth
public_router = APIRouter(prefix="/api/session", tags=["session"])


class StartSessionRequest(BaseModel):
    name: str
    type: Literal["workshop", "talk"]


class ResumeSessionRequest(BaseModel):
    folder: str


class SessionStartResponse(BaseModel):
    session_name: str
    session_id: str


class FolderInfo(BaseModel):
    name: str
    session_type: str | None = None


class SessionFoldersResponse(BaseModel):
    folders: list[FolderInfo]


class SessionActiveResponse(BaseModel):
    session_id: str | None


@global_router.post("/create", response_model=SessionStartResponse)
async def start_session(body: StartSessionRequest):
    """Host starts a new session (creates folder, assigns session_id, clean slate)."""
    name = normalize_session_name(body.name)
    session_id = _generate_session_id()

    session_pending.put("session_request", {
        "action": "create",
        "name": name,
        "type": body.type,
        "session_id": session_id,
    })
    # Pre-register session_id with Railway immediately so host WS validates on first connect
    # (avoids race condition where host navigates before session_pending queue is processed)
    announce_session_id(session_id, session_type=body.type)
    return SessionStartResponse(session_name=name, session_id=session_id)


@global_router.post("/end", status_code=204)
async def end_session():
    """Host ends the current session. Railway closes WS connections on session end."""
    session_pending.put("session_request", {"action": "end"})
    return Response(status_code=204)


@global_router.post("/resume", response_model=SessionStartResponse)
async def resume_session(body: ResumeSessionRequest):
    """Host resumes an existing session folder. Uses session-state.json as persisted storage."""
    folder_name = normalize_session_name(body.folder)
    session_id = _resolve_session_id_for_folder(folder_name)

    session_pending.put("session_request", {
        "action": "create",
        "name": folder_name,
        "type": "workshop",
        "session_id": session_id,
    })
    announce_session_id(session_id)
    return SessionStartResponse(session_name=folder_name, session_id=session_id)


@global_router.get("/folders", response_model=SessionFoldersResponse)
async def list_session_folders():
    """List available session folders."""
    root = _get_sessions_root()
    if not root:
        return SessionFoldersResponse(folders=[])
    try:
        deduped = _dedupe_normalized_folder_names(
            sorted([f.name for f in root.iterdir() if f.is_dir()], reverse=True)
        )
        filtered = _filter_folders_to_current_year(deduped)
        folder_infos = []
        for name in filtered:
            meta = load_session_meta(root / name)
            folder_infos.append(FolderInfo(name=name, session_type=meta.get("session_type")))
        return SessionFoldersResponse(folders=folder_infos)
    except Exception as e:
        daemon_log.error("session", f"Failed to list session folders: {e}")
        return SessionFoldersResponse(folders=[])


# ── Public endpoint (no auth) ──

@public_router.get("/active", response_model=SessionActiveResponse)
async def get_session_active():
    """Public endpoint: returns the active session_id or null."""
    active_session_id = session_state.get_active_session_id()
    return SessionActiveResponse(session_id=active_session_id)
