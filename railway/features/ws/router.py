import asyncio
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

from railway.features.slides.cache import broadcast_slides_updated
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

# Grace period before kicking participants after a daemon WS drop. The daemon
# reconnects in ~3s on transient network blips; only evict clients if the
# daemon is still absent after this window.
_DAEMON_DISCONNECT_GRACE_SECONDS = float(os.environ.get("DAEMON_DISCONNECT_GRACE_SECONDS", "5"))
_pending_kick_task: asyncio.Task | None = None


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
    msg = json.dumps(event)
    for pid, ws in list(state.participants.items()):
        if pid.startswith("__") and pid != "__host__":  # keep host, skip other special keys
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            pass


_DAEMON_MSG_HANDLERS = {
    MSG_BROADCAST: _handle_broadcast,
    MSG_PROXY_RESPONSE: handle_proxy_response,
    MSG_SET_SESSION_ID: _handle_set_session_id,
    MSG_CODE_TIMESTAMP: _handle_code_timestamp,
    MSG_DAEMON_PING: None,  # heartbeat only — last_seen already updated
}


def _cancel_pending_kick():
    """Cancel any scheduled eviction task. Safe to call when none is pending."""
    global _pending_kick_task
    task = _pending_kick_task
    _pending_kick_task = None
    if task is not None and not task.done():
        task.cancel()


async def _evict_all_clients_after_grace(old_session_id: str | None):
    """Kick participants/host if the daemon stays disconnected past the grace window."""
    try:
        await asyncio.sleep(_DAEMON_DISCONNECT_GRACE_SECONDS)
    except asyncio.CancelledError:
        return
    if state.daemon_ws is not None:
        # Daemon reconnected during the grace window — nothing to do.
        return
    logger.info("Daemon still absent after %.1fs grace; evicting clients", _DAEMON_DISCONNECT_GRACE_SECONDS)
    for pid, ws in list(state.participants.items()):
        if pid.startswith("__") and pid != "__host__":
            continue
        if pid == "__host__":
            target_url = f"/host/{state.session_id}" if state.session_id else "/host"
            close_code = 1000
        else:
            target_url = f"/?session_id={quote(str(old_session_id or ''))}"
            close_code = 1008
        try:
            await ws.send_text(json.dumps({"type": "redirect", "url": target_url}))
            await ws.close(close_code)
        except Exception:
            pass
        state.participants.pop(pid, None)
    await broadcast_slides_updated()


@router.websocket("/ws/daemon")
async def daemon_websocket_endpoint(websocket: WebSocket):
    if not _is_host_authorized_for_ws(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # Cancel any pending eviction from a recent daemon WS drop — daemon is back in time.
    _cancel_pending_kick()

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

    await broadcast_slides_updated()

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
        # Defer kicking clients: transient daemon WS drops (keepalive timeouts,
        # brief network blips) reconnect in ~3s. Only evict if the daemon stays
        # gone past the grace window.
        _cancel_pending_kick()
        global _pending_kick_task
        _pending_kick_task = asyncio.create_task(_evict_all_clients_after_grace(state.session_id))


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
        presence_msg: dict = {"type": MSG_PARTICIPANT_PRESENCE, "uuid": pid, "online": True}
        # Browser-reported IANA timezone — piggybacks on the WS join so the host
        # sees a participant's local clock without requiring location sharing.
        tz = websocket.query_params.get("tz", "").strip()[:64]
        if tz:
            presence_msg["tz"] = tz
        await push_to_daemon(presence_msg)
        broadcast_participant_update()

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
            broadcast_participant_update()


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
            # SECURITY: never steer a stale/unknown session onto the active one —
            # that leaks one cohort into another (session hijack via redirect).
            # Send the participant to the neutral landing; the SPA obeys this
            # generic `redirect` frame, so no client change is needed.
            await websocket.send_text(json.dumps({"type": "redirect", "url": "/?error=invalid"}))
            await websocket.close(code=1008)
        return

    pid = participant_id.strip()
    is_host = (pid == "__host__")

    if not is_host and (not pid or pid.startswith("__")):
        await websocket.accept()
        await websocket.close(code=1008)
        return

    await _handle_participant_connection(websocket, pid, is_host=is_host)
