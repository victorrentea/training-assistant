"""Host browser WebSocket push — single connection stored at module level.

The host browser connects to daemon's localhost:8081 via WebSocket.
This module stores that connection so daemon code can push messages
directly to the host without going through Railway.
"""
import json
import logging

logger = logging.getLogger(__name__)

_host_ws = None


def set_host_ws(ws):
    """Store the host browser's WS connection. Called when host connects."""
    global _host_ws
    _host_ws = ws


def clear_host_ws():
    """Clear the host WS reference. Called when host disconnects."""
    global _host_ws
    _host_ws = None


async def send_to_host(msg: dict):
    """Push a JSON message to the host browser. No-op if not connected."""
    if _host_ws is None:
        return
    try:
        await _host_ws.send_text(json.dumps(msg))
    except Exception:
        logger.debug("Failed to send to host WS")
