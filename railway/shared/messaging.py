"""
Broadcast infrastructure.

broadcast() sends semantic events to all connected clients.
broadcast_participant_update() sends participant count to all connected participants.
"""
import json
import logging
from typing import Optional
from fastapi import WebSocket

from railway.shared.state import state

logger = logging.getLogger(__name__)

SPECIAL_PIDS = {"__host__"}


def participant_ids() -> list[str]:
    """Return sorted UUIDs of non-special connected participants."""
    return sorted(pid for pid in state.participants if pid not in SPECIAL_PIDS)


async def _broadcast_foreach(sender):
    """Iterate participants, call sender(pid, ws) for each, and clean up dead connections.

    The sender callback should send a message or return without sending to skip.
    Raising any exception signals a dead connection.
    """
    dead = []
    for pid, ws in state.participants.items():
        try:
            await sender(pid, ws)
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def broadcast(message: dict, exclude: Optional[str] = None):
    """Send identical message to all connected clients."""
    text = json.dumps(message)
    async def _send(pid, ws):
        if pid == exclude:
            return
        await ws.send_text(text)
    await _broadcast_foreach(_send)


async def broadcast_participant_update():
    """Send participant count update to all connected participants (not host)."""
    pids = participant_ids()
    count = len(pids)

    msg = json.dumps({
        "type": "participant_count_updated",
        "count": count,
        "host_connected": "__host__" in state.participants,
    })

    async def _send(pid, ws):
        if pid == "__host__":
            return
        await ws.send_text(msg)
    await _broadcast_foreach(_send)


async def _send_to_special(key: str, message: dict):
    """Send a message to a special client (e.g. __host__, __overlay__), cleaning up on failure."""
    ws = state.participants.get(key)
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps(message))
    except Exception:
        state.participants.pop(key, None)


async def send_to_host(message: dict):
    """Send to __host__."""
    await _send_to_special("__host__", message)


async def send_emoji_to_host(emoji: str):
    """Forward an emoji reaction to the host client if connected."""
    await _send_to_special("__host__", {"type": "emoji_reaction", "emoji": emoji})
