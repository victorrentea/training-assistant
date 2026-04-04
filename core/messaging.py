"""
Broadcast infrastructure + registry pattern for state serialization.

Each feature registers its own state builders at import time via register_state_builder().
build_participant_state() and build_host_state() merge contributions from all registered features.
"""
import json
import logging
from typing import Optional, Callable
from fastapi import WebSocket

from core.state import state

logger = logging.getLogger(__name__)

SPECIAL_PIDS = {"__host__", "__overlay__"}

# Registry: feature name → (build_for_participant, build_for_host) callables
_state_builders: dict[str, tuple[Callable, Callable]] = {}


def register_state_builder(feature: str, for_participant: Callable, for_host: Callable):
    """Called by each feature's state_builder.py at import time."""
    _state_builders[feature] = (for_participant, for_host)


def participant_ids() -> list[str]:
    """Return sorted UUIDs of named participants, excluding special clients."""
    return sorted(
        pid for pid in state.participants
        if pid not in SPECIAL_PIDS and pid in state.participant_names
    )


def historical_participant_ids() -> list[str]:
    """Return UUIDs seen in this session (online or offline), excluding special clients."""
    known = (
        set(state.participant_history)
        | set(state.participant_names.keys())
        | set(state.scores.keys())
        | set(state.participant_avatars.keys())
        | set(state.locations.keys())
        | set(state.participant_ips.keys())
    )
    known = [pid for pid in known if pid not in SPECIAL_PIDS]
    return sorted(
        known,
        key=lambda pid: (-state.scores.get(pid, 0), state.participant_names.get(pid, ""), pid),
    )


def build_participant_state(pid: str) -> dict:
    """Merge state from all registered feature builders for a participant."""
    result = {}
    for feature, (builder, _) in _state_builders.items():
        result.update(builder(pid))
    return result


def build_host_state() -> dict:
    """Merge state from all registered feature builders for the host."""
    result = {}
    for feature, (_, builder) in _state_builders.items():
        result.update(builder())
    return result


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


async def broadcast_state():
    """Send personalized state to each connected client."""
    async def _send(pid, ws):
        if pid == "__overlay__":
            return
        if pid == "__host__":
            await ws.send_text(json.dumps(build_host_state()))
        else:
            await ws.send_text(json.dumps(build_participant_state(pid)))
    await _broadcast_foreach(_send)


async def broadcast(message: dict, exclude: Optional[str] = None):
    """Send identical message to all connected clients."""
    text = json.dumps(message)
    async def _send(pid, ws):
        if pid == exclude:
            return
        await ws.send_text(text)
    await _broadcast_foreach(_send)


async def broadcast_participant_update():
    """Send participant update: simple count to participants, full details to host."""
    from core.state_builder import _build_host_participants_list
    pids = participant_ids()
    count = len(pids)

    participant_msg = json.dumps({
        "type": "participant_count",
        "count": count,
        "host_connected": "__host__" in state.participants,
    })

    host_msg = json.dumps({
        "type": "participant_count",
        "count": count,
        "participants": _build_host_participants_list(),
    })

    async def _send(pid, ws):
        if pid == "__host__":
            await ws.send_text(host_msg)
        else:
            await ws.send_text(participant_msg)
    await _broadcast_foreach(_send)


async def send_state_to_participant(ws: WebSocket, pid: str):
    """Send personalized state to a specific participant."""
    await ws.send_text(json.dumps(build_participant_state(pid)))


async def send_state_to_host(ws: WebSocket):
    """Send host state to the host websocket."""
    await ws.send_text(json.dumps(build_host_state()))


async def _send_to_special(key: str, message: dict):
    """Send a message to a special client (e.g. __host__, __overlay__), cleaning up on failure."""
    ws = state.participants.get(key)
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps(message))
    except Exception:
        state.participants.pop(key, None)


async def send_emoji_to_overlay(emoji: str):
    """Forward an emoji reaction to the overlay client if connected."""
    await _send_to_special("__overlay__", {"type": "emoji_reaction", "emoji": emoji})


async def send_emoji_to_host(emoji: str):
    """Forward an emoji reaction to the host client if connected."""
    await _send_to_special("__host__", {"type": "emoji_reaction", "emoji": emoji})
