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


async def broadcast_state():
    """Send personalized state to each connected client."""
    dead = []
    for pid, ws in state.participants.items():
        if pid == "__overlay__":
            continue
        try:
            if pid == "__host__":
                await ws.send_text(json.dumps(build_host_state()))
            else:
                await ws.send_text(json.dumps(build_participant_state(pid)))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def broadcast(message: dict, exclude: Optional[str] = None):
    """Send identical message to all connected clients."""
    dead = []
    for pid, ws in state.participants.items():
        if pid == exclude:
            continue
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


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

    dead = []
    for pid, ws in state.participants.items():
        try:
            if pid == "__host__":
                await ws.send_text(host_msg)
            else:
                await ws.send_text(participant_msg)
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def broadcast_leaderboard():
    """Send personalized leaderboard to each connected participant."""
    from features.leaderboard.state_builder import _build_leaderboard_data
    entries, total, rank_map = _build_leaderboard_data()

    dead = []
    for pid, ws in state.participants.items():
        if pid == "__overlay__":
            continue
        try:
            is_participant = not pid.startswith("__")
            msg = {
                "type": "leaderboard",
                "entries": entries,
                "total_participants": total,
                "your_rank": rank_map.get(pid) if is_participant else None,
                "your_score": state.scores.get(pid, 0) if is_participant else None,
                "your_name": state.participant_names.get(pid, "") if is_participant else None,
            }
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def send_state_to_participant(ws: WebSocket, pid: str):
    """Send personalized state to a specific participant."""
    await ws.send_text(json.dumps(build_participant_state(pid)))


async def send_state_to_host(ws: WebSocket):
    """Send host state to the host websocket."""
    await ws.send_text(json.dumps(build_host_state()))


async def send_emoji_to_overlay(emoji: str):
    """Forward an emoji reaction to the overlay client if connected."""
    ws = state.participants.get("__overlay__")
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps({"type": "emoji_reaction", "emoji": emoji}))
    except Exception:
        state.participants.pop("__overlay__", None)


async def send_emoji_to_host(emoji: str):
    """Forward an emoji reaction to the host client if connected."""
    ws = state.participants.get("__host__")
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps({"type": "emoji_reaction", "emoji": emoji}))
    except Exception:
        state.participants.pop("__host__", None)
