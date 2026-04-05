import base64
import binascii
import hashlib as _hashlib_mod
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from railway.shared.messaging import (
    broadcast,
    broadcast_participant_update,
)
from railway.shared.metrics import (
    ws_connections_active,
    ws_messages_total,
)
from railway.shared.state import state
from railway.features.ws.daemon_protocol import (
    MSG_SLIDES_CATALOG, MSG_DAEMON_PING,
    MSG_PROXY_RESPONSE,
    MSG_BROADCAST, MSG_SEND_TO_HOST, MSG_SET_SESSION_ID, MSG_CODE_TIMESTAMP,
    MSG_DOWNLOAD_PDF, MSG_PDF_DOWNLOAD_COMPLETE,
    push_to_daemon,
)
from railway.features.ws.proxy_bridge import handle_proxy_response

router = APIRouter()
session_router = APIRouter()
logger = logging.getLogger(__name__)


async def _kick_old_connection(pid: str):
    if pid in state.participants:
        old_ws = state.participants[pid]
        try:
            await old_ws.send_text(json.dumps({"type": "kicked"}))
            await old_ws.close(code=1001)
        except Exception:
            pass
        del state.participants[pid]


def _is_host_authorized_for_ws(websocket: WebSocket) -> bool:
    raw = websocket.headers.get("authorization", "").strip()
    if not raw.lower().startswith("basic "):
        return False
    token = raw[6:].strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    if ":" not in decoded:
        return False
    username, password = decoded.split(":", 1)
    expected_user = os.environ.get("HOST_USERNAME") or "host"
    expected_pass = os.environ.get("HOST_PASSWORD") or "host"
    return (
        secrets.compare_digest(username.encode(), expected_user.encode())
        and secrets.compare_digest(password.encode(), expected_pass.encode())
    )


async def _handle_daemon_slides_catalog(data):
    from railway.features.slides.cache import handle_slides_catalog
    await handle_slides_catalog(data.get("entries", []))


async def _handle_send_to_host(data: dict):
    """Forward event to __host__ WS."""
    event = data.get("event")
    if not event:
        return
    ws = state.participants.get("__host__")
    if ws:
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            pass


async def _handle_code_timestamp(data: dict):
    """Daemon pushes the git timestamp of its last commit."""
    ts = data.get("timestamp")
    if ts:
        state.daemon_code_timestamp = ts


async def _handle_set_session_id(data: dict):
    """Daemon sets/changes active session. Drop old participant connections."""
    new_id = data.get("session_id")
    new_name = data.get("session_name")
    old_id = state.session_id

    if new_id:
        state.session_id = new_id
    if new_name is not None:
        state.session_name = new_name

    # If session_id changed, disconnect participants from old session
    if old_id and new_id and old_id.lower() != new_id.lower():
        redirect_msg = json.dumps({"type": "redirect", "url": f"/{new_id}"})
        for pid, ws in list(state.participants.items()):
            if pid.startswith("__"):
                continue
            try:
                await ws.send_text(redirect_msg)
                await ws.close(1008)
            except Exception:
                pass
            state.participants.pop(pid, None)


_SYNC_EXCLUDED = {"version.js", "deploy-info.json", "work-hours.js"}

def _build_static_hashes() -> dict[str, str]:
    """Build {relative_path: md5_hex} for all files in static/ (recursive)."""
    static_dir = Path(__file__).resolve().parent.parent.parent.parent / "static"
    hashes = {}
    if static_dir.is_dir():
        for f in static_dir.rglob("*"):
            if f.is_file() and f.name not in _SYNC_EXCLUDED:
                rel = str(f.relative_to(static_dir))
                md5 = _hashlib_mod.md5(f.read_bytes()).hexdigest()
                hashes[rel] = md5
    return hashes



async def _handle_broadcast(data: dict):
    """Fan out a daemon broadcast event to all connected participant WSs."""
    event = data.get("event")
    if not event:
        return
    # Mirror slides_current into Railway state so /api/status can return it.
    # Two event shapes from daemon:
    #   {type:"slides_current", slug:..., url:..., ...}  — active slide
    #   {type:"slides_current", slides_current: null}    — no active slide
    if event.get("type") == "slides_current":
        if "slides_current" in event:
            state.slides_current = event["slides_current"]  # may be None
        else:
            state.slides_current = {k: v for k, v in event.items() if k != "type"}
    msg = json.dumps(event)
    for pid, ws in list(state.participants.items()):
        if pid.startswith("__"):  # skip __host__, __overlay__
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            pass


async def _run_download_pdf(slug: str, drive_export_url: str) -> None:
    """Background task: download PDF for slug and notify daemon of result."""
    import asyncio
    from railway.features.slides.cache import download_or_wait_cached
    # Ensure the catalog entry exists so download_or_wait_cached can find the URL
    if slug not in state.slides_catalog:
        state.slides_catalog[slug] = {"drive_export_url": drive_export_url}
    elif not state.slides_catalog[slug].get("drive_export_url"):
        state.slides_catalog[slug]["drive_export_url"] = drive_export_url
    try:
        path = await download_or_wait_cached(slug)
        if path is not None:
            await push_to_daemon({"type": MSG_PDF_DOWNLOAD_COMPLETE, "slug": slug, "status": "ok"})
        else:
            await push_to_daemon({"type": MSG_PDF_DOWNLOAD_COMPLETE, "slug": slug, "status": "error", "error": "download returned None"})
    except Exception as exc:
        await push_to_daemon({"type": MSG_PDF_DOWNLOAD_COMPLETE, "slug": slug, "status": "error", "error": str(exc)})



async def _handle_download_pdf(data: dict) -> None:
    """Handle download_pdf message from daemon — start download in background."""
    import asyncio
    slug = data.get("slug", "").strip()
    drive_export_url = data.get("drive_export_url", "").strip()
    if not slug or not drive_export_url:
        logger.warning("[ws] download_pdf missing slug or drive_export_url")
        return
    asyncio.create_task(_run_download_pdf(slug, drive_export_url))


_DAEMON_MSG_HANDLERS = {
    MSG_BROADCAST: _handle_broadcast,
    MSG_SEND_TO_HOST: _handle_send_to_host,
    MSG_PROXY_RESPONSE: handle_proxy_response,
    MSG_SET_SESSION_ID: _handle_set_session_id,
    MSG_CODE_TIMESTAMP: _handle_code_timestamp,
    MSG_DAEMON_PING: None,  # heartbeat only — last_seen already updated
    MSG_SLIDES_CATALOG: _handle_daemon_slides_catalog,
    MSG_DOWNLOAD_PDF: _handle_download_pdf,
}


@router.websocket("/ws/daemon")
async def daemon_websocket_endpoint(websocket: WebSocket):
    if not _is_host_authorized_for_ws(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # Kick old daemon connection if present.
    old_ws = state.daemon_ws
    if old_ws is not None and old_ws is not websocket:
        try:
            await old_ws.send_json({"type": "kicked"})
            await old_ws.close(code=1001)
        except Exception:
            pass

    state.daemon_ws = websocket
    state.daemon_last_seen = datetime.now(timezone.utc)
    logger.info("Daemon WS connected")
    await broadcast({"type": "slides_catalog_changed"})

    # Send static file inventory for daemon to diff and upload changes
    try:
        static_hashes = _build_static_hashes()
        await websocket.send_json({"type": "sync_files", "static_hashes": static_hashes, "pdf_slugs": {}})
    except Exception:
        logger.warning("Failed to send sync_files to daemon")

    try:
        while True:
            data = await websocket.receive_json()
            state.daemon_last_seen = datetime.now(timezone.utc)
            msg_type = data.get("type")
            handler = _DAEMON_MSG_HANDLERS.get(msg_type)
            if handler is not None:
                try:
                    await handler(data)
                except Exception:
                    logger.exception("Error handling daemon message type: %s", msg_type)
            elif msg_type not in _DAEMON_MSG_HANDLERS:
                logger.warning("Unknown daemon message type: %s", msg_type)
    except WebSocketDisconnect:
        pass
    finally:
        if state.daemon_ws is websocket:
            state.daemon_ws = None
        logger.info("Daemon WS disconnected")
        await broadcast({"type": "slides_catalog_changed"})


async def _send_initial_messages(websocket: WebSocket) -> None:
    """Send slides_cache_status as a separate initial message after state."""
    try:
        await websocket.send_text(json.dumps({"type": "slides_cache_status", "slides_cache_status": state.slides_cache_status}))
    except Exception:
        pass


async def _handle_participant_connection(websocket: WebSocket, pid: str, is_host: bool):
    """Shared logic for participant/host WebSocket connections.

    Handles: accept, name registration, message loop, disconnect cleanup.
    Caller must have already validated auth and session_id as appropriate.
    """
    role = "host" if is_host else "participant"

    # Host reconnect: kick old host connection
    if is_host:
        await _kick_old_connection("__host__")

    await websocket.accept()

    state.participants[pid] = websocket
    if not is_host:
        state.participant_history.add(pid)
        forwarded = websocket.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (websocket.client.host if websocket.client else "")
        state.participant_ips[pid] = ip
    ws_connections_active.labels(role=role).inc()

    if is_host:
        state.participant_names["__host__"] = "Host"
        logger.info(f"Host connected ({len(state.participants)} total)")
        await _send_initial_messages(websocket)
        await broadcast_participant_update()
    else:
        # Participant registered via daemon REST — send initial state and broadcast presence
        name = state.participant_names.get(pid, "")
        logger.info(f"WS connected: {pid} name={name!r} ({len(state.participants)} total)")
        await _send_initial_messages(websocket)
        await broadcast_participant_update()

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")
            if msg_type:
                ws_messages_total.labels(type=msg_type).inc()
            # All participant actions go through daemon REST — just keep the WS alive for broadcasts

    except WebSocketDisconnect:
        state.participants.pop(pid, None)
        state.participant_ips.pop(pid, None)
        ws_connections_active.labels(role=role).dec()
        logger.info(f"Disconnected: {pid} ({len(state.participants)} remaining)")
        await broadcast_participant_update()


@session_router.websocket("/ws/{session_id}/{participant_id}")
async def session_websocket_endpoint(websocket: WebSocket, session_id: str, participant_id: str):
    """WebSocket endpoint for participants and host (__host__), requiring a valid session_id."""
    # Validate session_id — accept first so client gets a clean close code
    if not state.session_id or session_id.lower() != state.session_id.lower():
        is_host_attempt = participant_id.strip() == "__host__"
        if is_host_attempt:
            await websocket.accept()
            if state.session_id:
                await websocket.send_text(json.dumps({"type": "redirect", "url": f"/host/{state.session_id}"}))
            else:
                await websocket.send_text(json.dumps({"type": "redirect", "url": "/host"}))
            await websocket.close(code=1000)
        else:
            await websocket.accept()
            if state.session_id:
                await websocket.send_text(json.dumps({"type": "redirect", "url": f"/{state.session_id}"}))
            await websocket.close(code=1008)
        return

    pid = participant_id.strip()
    is_host = (pid == "__host__")

    if not is_host and (not pid or pid.startswith("__")):
        await websocket.accept()
        await websocket.close(code=1008)
        return

    await _handle_participant_connection(websocket, pid, is_host=is_host)
