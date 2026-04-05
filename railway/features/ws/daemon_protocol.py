# features/ws/daemon_protocol.py
"""Daemon WebSocket protocol — message types and push helpers."""
import logging
from railway.shared.state import state

logger = logging.getLogger(__name__)

# --- Inbound message types (daemon → backend) ---
MSG_SLIDES_CATALOG = "slides_catalog"
MSG_SLIDE_INVALIDATED = "slide_invalidated"
MSG_DAEMON_PING = "daemon_ping"

# --- Generic broadcast (daemon → all participants via backend) ---
MSG_BROADCAST = "broadcast"

# --- Send to host/overlay only (daemon → backend → host/overlay) ---
MSG_SEND_TO_HOST = "send_to_host"

# --- Proxy (bidirectional) ---
MSG_PROXY_REQUEST = "proxy_request"
MSG_PROXY_RESPONSE = "proxy_response"

# --- Session identity (daemon → backend) ---
MSG_SET_SESSION_ID = "set_session_id"

# --- Static file sync (backend → daemon) ---
MSG_SYNC_FILES = "sync_files"


async def push_to_daemon(msg: dict) -> bool:
    """Send a JSON message to the daemon via WebSocket. Returns True if sent."""
    ws = state.daemon_ws
    if ws is None:
        return False
    try:
        await ws.send_json(msg)
        return True
    except Exception:
        logger.warning("Failed to push to daemon: %s", msg.get("type", "unknown"))
        return False
