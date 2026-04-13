import base64
import binascii
import hashlib as _hashlib_mod
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from railway.features.slides.cache import broadcast_slides_cache_status
from railway.features.ws.daemon_protocol import (
    MSG_BROADCAST,
    MSG_CODE_TIMESTAMP,
    MSG_DAEMON_PING,
    MSG_PARTICIPANT_PRESENCE,
    MSG_PROXY_RESPONSE,
    MSG_SET_SESSION_ID,
    push_to_daemon,
)
from railway.features.ws.proxy_bridge import handle_proxy_response
from railway.shared.messaging import (
    SPECIAL_PIDS,
    broadcast_participant_update,
)
from railway.shared.metrics import (
    ws_connections_active,
    ws_messages_total,
)
from railway.shared.state import state

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


async def _handle_code_timestamp(data: dict):
    """Daemon pushes the git timestamp of its last commit."""
    ts = data.get("timestamp")
    if ts:
        state.daemon_code_timestamp = ts


async def _handle_set_session_id(data: dict):
    """Daemon sets/changes active session. Drop stale host/participant connections."""
    new_id = data.get("session_id")
    state.session_type = data.get("session_type", "workshop")
    old_id = state.session_id
    had_active_session = bool(old_id)

    # Daemon omits session_id when no session is active.
    state.session_id = new_id or None

    if old_id and state.session_id:
        session_changed = old_id.lower() != state.session_id.lower()
    else:
        session_changed = old_id != state.session_id

    # If active session changed (including ending it), disconnect old session clients.
    if had_active_session and session_changed:
        for pid, ws in list(state.participants.items()):
            if pid.startswith("__") and pid != "__host__":
                continue
            if pid == "__host__":
                target_url = f"/host/{state.session_id}" if state.session_id else "/host"
                close_code = 1000
            else:
                if state.session_id:
                    target_url = f"/{state.session_id}"
                else:
                    target_url = f"/?session_id={quote(str(old_id or ''))}"
                close_code = 1008
            try:
                await ws.send_text(json.dumps({"type": "redirect", "url": target_url}))
                await ws.close(close_code)
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
    """Fan out a daemon broadcast event to participants and host WSs."""
    event = data.get("event")
    if not event:
        return
    event_type = event.get("type")
    # Mirror slides_current into Railway state so /api/status can return it.
    # Two event shapes from daemon:
    #   {type:"slides_current", slug:..., url:..., ...}  — active slide
    #   {type:"slides_current", slides_current: null}    — no active slide
    if event_type == "slides_current":
        if "slides_current" in event:
            state.slides_current = event["slides_current"]  # may be None
        else:
            state.slides_current = {k: v for k, v in event.items() if k != "type"}
    msg = json.dumps(event)
    for pid, ws in list(state.participants.items()):
        if pid.startswith("__") and pid != "__host__":  # keep host, skip other special keys
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            pass


async def _handle_participant_registered(data: dict):
    """Apply daemon identity write-back for a newly registered participant."""
    pid = str(data.get("participant_id") or "").strip()
    if not pid or pid.startswith("__"):
        return
    name = data.get("name")
    avatar = data.get("avatar")
    score = data.get("score")
    if isinstance(name, str):
        state.participant_names[pid] = name
    if isinstance(avatar, str):
        state.participant_avatars[pid] = avatar
    if isinstance(score, (int, float)):
        state.scores[pid] = int(score)
    await broadcast_participant_update()


async def _handle_participant_renamed(data: dict):
    """Apply daemon identity write-back for participant rename."""
    pid = str(data.get("participant_id") or "").strip()
    name = data.get("name")
    if not pid or pid.startswith("__") or not isinstance(name, str):
        return
    state.participant_names[pid] = name
    await broadcast_participant_update()


async def _handle_participant_avatar_updated(data: dict):
    """Apply daemon identity write-back for participant avatar updates."""
    pid = str(data.get("participant_id") or "").strip()
    avatar = data.get("avatar")
    if not pid or pid.startswith("__") or not isinstance(avatar, str):
        return
    state.participant_avatars[pid] = avatar
    await broadcast_participant_update()


async def _handle_participant_location(data: dict):
    """Apply daemon identity write-back for participant location updates."""
    pid = str(data.get("participant_id") or "").strip()
    location = data.get("location")
    if not pid or pid.startswith("__") or not isinstance(location, str):
        return
    state.locations[pid] = location
    await broadcast_participant_update()


_DAEMON_MSG_HANDLERS = {
    MSG_BROADCAST: _handle_broadcast,
    MSG_PROXY_RESPONSE: handle_proxy_response,
    MSG_SET_SESSION_ID: _handle_set_session_id,
    MSG_CODE_TIMESTAMP: _handle_code_timestamp,
    MSG_DAEMON_PING: None,  # heartbeat only — last_seen already updated
    "participant_registered": _handle_participant_registered,
    "participant_renamed": _handle_participant_renamed,
    "participant_avatar_updated": _handle_participant_avatar_updated,
    "participant_location": _handle_participant_location,
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

    # Sync current online participants to daemon — resets stale daemon state after Railway restart
    current_online = [pid for pid in state.participants if pid not in SPECIAL_PIDS]
    try:
        await websocket.send_json({"type": "daemon_state_push", "online_participants": current_online})
    except Exception:
        logger.warning("Failed to sync online participants to daemon on connect")

    await broadcast_slides_cache_status()

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
        # Kick all participant/host connections — daemon is gone, session is effectively dead
        old_id = state.session_id
        for pid, ws in list(state.participants.items()):
            if pid.startswith("__") and pid != "__host__":
                continue
            if pid == "__host__":
                target_url = f"/host/{state.session_id}" if state.session_id else "/host"
                close_code = 1000
            else:
                target_url = f"/?session_id={quote(str(old_id or ''))}"
                close_code = 1008
            try:
                await ws.send_text(json.dumps({"type": "redirect", "url": target_url}))
                await ws.close(close_code)
            except Exception:
                pass
            state.participants.pop(pid, None)
        await broadcast_slides_cache_status()


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
    else:
        # Participant registered via daemon REST — broadcast presence
        name = state.participant_names.get(pid, "")
        logger.info(f"WS connected: {pid} name={name!r} ({len(state.participants)} total)")
        await push_to_daemon({"type": MSG_PARTICIPANT_PRESENCE, "uuid": pid, "online": True})
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
        if not is_host:
            await push_to_daemon({"type": MSG_PARTICIPANT_PRESENCE, "uuid": pid, "online": False})
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
