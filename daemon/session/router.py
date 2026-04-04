"""Session lifecycle endpoints — host-only, served directly by daemon localhost.

Migrated from features/session/router.py on Railway.
Instead of queuing requests for Railway to forward via WS, endpoints now
put requests directly into daemon/session/pending.py for the orchestrator loop.
"""
import os
import random
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.params import Query
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.session import pending as session_pending
from daemon.session import state as session_state
from daemon.session_state import load_session_meta
from daemon.transcript.query import load_normalized_entries


def normalize_session_name(name: str) -> str:
    """Replace non-breaking spaces and other Unicode whitespace with regular spaces."""
    return name.replace('\xa0', ' ').strip()


def _generate_session_id() -> str:
    """Generate a new 6-char alphanumeric session ID."""
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))


def _resolve_session_id_for_folder(folder_name: str) -> str:
    """Return stable session_id for a folder, loading from session_meta.json or generating a new one."""
    root = _get_sessions_root()
    if root:
        folder = root / folder_name
        if folder.exists():
            meta = load_session_meta(folder)
            if meta.get("session_id"):
                return meta["session_id"]
    return _generate_session_id()

logger = logging.getLogger(__name__)

# Set by daemon/__main__.py during startup
_ws_client = None


def set_ws_client(client) -> None:
    """Set the module-level ws_client reference."""
    global _ws_client
    _ws_client = client


def _normalize_transcript_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\t", " ")).strip()


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


def _get_transcription_root() -> Path | None:
    folder_str = os.environ.get(
        "TRANSCRIPTION_FOLDER",
        "/Users/victorrentea/Documents/transcriptions",
    )
    p = Path(folder_str).expanduser()
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


def _is_session_active(stack: list[dict]) -> bool:
    """Return True if session stack has an active (non-ended) session."""
    if not stack:
        return False
    top = stack[-1]
    if top.get("ended_at"):
        return False
    paused = any(p.get("to") is None for p in top.get("paused_intervals", []))
    # Active includes paused sessions (they're still "open")
    return True


# ── Global host session endpoints (no session_id prefix) ──

global_router = APIRouter(prefix="/api/session", tags=["session"])
# Public endpoint needs a separate router without auth
public_router = APIRouter(prefix="/api/session", tags=["session"])

# ── Session-scoped host endpoints ──

session_router = APIRouter(prefix="/api/{session_id}/session", tags=["session"])


class StartSessionRequest(BaseModel):
    name: str


class RenameSessionRequest(BaseModel):
    name: str


class SessionCreateBody(BaseModel):
    name: str
    type: str = "workshop"


class ResumeFolderBody(BaseModel):
    folder_name: str


@global_router.post("/start")
async def start_session(body: StartSessionRequest):
    """Host starts a new (nested) session."""
    name = normalize_session_name(body.name)
    session_pending.put("session_request", {"action": "start", "name": name})
    return JSONResponse({"ok": True})


@global_router.post("/end")
async def end_session():
    """Host ends the current session."""
    session_pending.put("session_request", {"action": "end"})
    # Optimistic broadcast: immediately tell clients session ended
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": {"type": "session_updated", "session_main": None}})
    return JSONResponse({"ok": True})


@global_router.post("/pause")
async def pause_session():
    """Host pauses the current session."""
    session_pending.put("session_request", {"action": "pause"})
    # Optimistic broadcast
    stack = session_state.get_session_stack()
    if stack:
        session_main = _build_session_main(stack)
        if session_main:
            session_main = {**session_main, "status": "paused"}
            if _ws_client:
                _ws_client.send({"type": "broadcast", "event": {"type": "session_updated", "session_main": session_main}})
    return JSONResponse({"ok": True})


@global_router.post("/resume")
async def resume_session():
    """Host resumes a paused session."""
    session_pending.put("session_request", {"action": "resume"})
    # Optimistic broadcast
    stack = session_state.get_session_stack()
    if stack:
        session_main = _build_session_main(stack)
        if session_main:
            session_main = {**session_main, "status": "active"}
            if _ws_client:
                _ws_client.send({"type": "broadcast", "event": {"type": "session_updated", "session_main": session_main}})
    return JSONResponse({"ok": True})


@global_router.post("/create")
async def create_session(body: SessionCreateBody):
    """Host creates a new session folder (full reset)."""
    name = normalize_session_name(body.name)
    session_id = _resolve_session_id_for_folder(name)

    session_pending.put("session_request", {
        "action": "create",
        "name": name,
        "type": body.type,
        "session_id": session_id,
    })
    return JSONResponse({"ok": True, "session_name": name, "session_id": session_id})


@global_router.patch("/rename")
async def rename_session(body: RenameSessionRequest):
    """Host renames the current session."""
    session_pending.put("session_request", {"action": "rename", "name": normalize_session_name(body.name)})
    return JSONResponse({"ok": True})


@global_router.post("/resume-folder")
async def resume_session_folder(body: ResumeFolderBody):
    """Host resumes a past session from a folder. Reuses old session_id from session_meta.json if available."""
    folder_name = normalize_session_name(body.folder_name)
    session_id = _resolve_session_id_for_folder(folder_name)
    session_pending.put("session_request", {"action": "create", "name": folder_name, "session_id": session_id})
    return JSONResponse({"ok": True, "session_name": folder_name, "session_id": session_id})


@global_router.get("/folders")
async def list_session_folders():
    """List available session folders."""
    root = _get_sessions_root()
    if not root:
        return JSONResponse({"folders": []})
    try:
        deduped = _dedupe_normalized_folder_names(
            sorted([f.name for f in root.iterdir() if f.is_dir()], reverse=True)
        )
        filtered = _filter_folders_to_current_year(deduped)
        return JSONResponse({"folders": filtered})
    except Exception as e:
        daemon_log.error("session", f"Failed to list session folders: {e}")
        return JSONResponse({"folders": []})


# Talk endpoints (conference mode nested talks)
@global_router.post("/start_talk")
async def start_talk():
    """Host starts a nested talk (conference mode)."""
    session_pending.put("session_request", {"action": "create_talk_folder"})
    return JSONResponse({"ok": True})


@global_router.post("/end_talk")
async def end_talk():
    """Host ends the nested talk."""
    session_pending.put("session_request", {"action": "end"})
    return JSONResponse({"ok": True})


# ── Public endpoint (no auth) ──

@public_router.get("/active")
async def get_session_active():
    """Public endpoint: returns whether a session is active."""
    stack = session_state.get_session_stack()
    active_session_id = session_state.get_active_session_id()
    is_active = _is_session_active(stack) and active_session_id is not None
    name = stack[-1].get("name") if stack else None
    return JSONResponse({
        "active": is_active,
        "auto_join": is_active,
        "session_id": active_session_id,
        "session_name": name,
    })


# ── Session-scoped endpoints ──

@session_router.get(
    "/interval-lines.txt",
    response_class=PlainTextResponse,
)
async def get_interval_lines_txt(
    start: str = Query(..., description="Interval start in ISO format"),
    end: str = Query(..., description="Interval end in ISO format"),
):
    """Return raw transcript lines for a time window."""
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return PlainTextResponse("Invalid start/end datetime format", status_code=400)

    if end_dt <= start_dt:
        return PlainTextResponse("End must be after start", status_code=400)

    root = _get_transcription_root()
    if root is None:
        return PlainTextResponse("Transcription folder not found", status_code=404)

    lines: list[str] = []
    for dt, txt in load_normalized_entries(root, since_date=start_dt.date()):
        if dt < start_dt or dt >= end_dt:
            continue
        normalized = _normalize_transcript_text(txt)
        if not normalized:
            continue
        lines.append(f"[{dt.strftime('%Y-%m-%d %H:%M:%S')}] {normalized}")

    if not lines:
        normalized_files = list(root.glob("* transcription.txt"))
        if not normalized_files:
            return PlainTextResponse("No normalized transcript files found", status_code=404)

    payload = "\n".join(lines) + ("\n" if lines else "")
    filename = (
        "session-interval-"
        + start_dt.strftime("%Y%m%d-%H%M")
        + "-"
        + end_dt.strftime("%Y%m%d-%H%M")
        + ".txt"
    )
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return PlainTextResponse(content=payload, headers=headers)


# ── Helpers ──

def _build_session_main(stack: list[dict]) -> dict | None:
    """Build session_main dict from stack top."""
    if not stack:
        return None
    top = stack[-1]
    paused = any(p.get("to") is None for p in top.get("paused_intervals", []))
    status = "paused" if paused else "active"
    return {
        "name": top.get("name"),
        "started_at": top.get("started_at"),
        "status": status,
    }
