"""
Broadcast infrastructure.

broadcast() sends semantic events to all connected clients.
broadcast_participant_update() sends participant count to participants, full details to host.
"""
import json
import logging
from typing import Optional
from fastapi import WebSocket

from railway.shared.state import state

logger = logging.getLogger(__name__)

SPECIAL_PIDS = {"__host__", "__overlay__"}


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


def _build_host_participants_list() -> list[dict]:
    """Build the list of all historical participants for the host."""
    participants_list: list[dict] = []
    for pid in historical_participant_ids():
        name = state.participant_names.get(pid, "").strip()
        participant = {
            "uuid": pid,
            "name": name if name else f"Guest {pid[:8]}",
            "score": state.scores.get(pid, 0),
            "location": state.locations.get(pid, ""),
            "avatar": state.participant_avatars.get(pid, ""),
            "ip": state.participant_ips.get(pid, ""),
            "online": pid in state.participants,
        }
        paste_entries = state.paste_texts.get(pid, [])
        if paste_entries:
            participant["paste_texts"] = paste_entries
        upload_entries = state.uploaded_files.get(pid, [])
        if upload_entries:
            participant["uploaded_files"] = [
                {"id": e["id"], "filename": e["filename"], "size": e["size"],
                 "downloaded_at": e.get("downloaded_at")}
                for e in upload_entries
            ]
        participants_list.append(participant)
    return participants_list


async def broadcast_participant_update():
    """Send participant update: simple count to participants, full details to host."""
    pids = participant_ids()
    count = len(pids)

    participant_msg = json.dumps({
        "type": "participant_updated",
        "count": count,
        "host_connected": "__host__" in state.participants,
    })

    host_msg = json.dumps({
        "type": "participant_updated",
        "count": count,
        "participants": _build_host_participants_list(),
    })

    async def _send(pid, ws):
        if pid == "__host__":
            await ws.send_text(host_msg)
        else:
            await ws.send_text(participant_msg)
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
    """Send to __host__ and __overlay__."""
    msg = json.dumps(message) if isinstance(message, dict) else message
    for special in ("__host__", "__overlay__"):
        ws = state.participants.get(special)
        if ws:
            try:
                await ws.send_text(msg)
            except Exception:
                state.participants.pop(special, None)


async def send_emoji_to_overlay(emoji: str):
    """Forward an emoji reaction to the overlay client if connected."""
    await _send_to_special("__overlay__", {"type": "emoji_reaction", "emoji": emoji})


async def send_emoji_to_host(emoji: str):
    """Forward an emoji reaction to the host client if connected."""
    await _send_to_special("__host__", {"type": "emoji_reaction", "emoji": emoji})
