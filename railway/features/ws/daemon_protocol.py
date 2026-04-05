# features/ws/daemon_protocol.py
"""Daemon WebSocket protocol — message types and push helpers."""
import logging
from railway.shared.state import state

logger = logging.getLogger(__name__)

# --- Inbound message types (daemon → backend) ---
MSG_SLIDE_INVALIDATED = "slide_invalidated"
MSG_DAEMON_PING = "daemon_ping"

# --- Generic broadcast (daemon → all participants via backend) ---
MSG_BROADCAST = "broadcast"

# --- Send to host only (daemon → backend → host) ---
MSG_SEND_TO_HOST = "send_to_host"

# --- Proxy (bidirectional) ---
MSG_PROXY_REQUEST = "proxy_request"
MSG_PROXY_RESPONSE = "proxy_response"

# --- Session identity (daemon → backend) ---
MSG_SET_SESSION_ID = "set_session_id"

# --- Code timestamp (daemon → backend) ---
MSG_CODE_TIMESTAMP = "code_timestamp"

# --- Static file sync (backend → daemon) ---
MSG_SYNC_FILES = "sync_files"

# --- PDF download (daemon → backend → daemon) ---
MSG_DOWNLOAD_PDF = "download_pdf"
MSG_PDF_DOWNLOAD_COMPLETE = "pdf_download_complete"


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
