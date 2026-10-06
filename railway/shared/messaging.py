"""
Broadcast infrastructure.

fan_out() sends one pre-serialized message to many sockets concurrently.
broadcast() sends semantic events to all connected clients.
broadcast_participant_update() sends total known participant count
to all connected participants (throttled to max 1/sec).
"""
import asyncio
import json
import logging
import os
from typing import Optional, Union

from fastapi import WebSocket
from pydantic import BaseModel

from railway.shared.state import state
from railway.shared.throttle import AsyncThrottle

logger = logging.getLogger(__name__)

SPECIAL_PIDS = {"__host__"}

# Upper bound for one client's send during a fan-out. send_text() returns at once
# while the socket's buffers have room; it only blocks once a client stops
# draining them (a phone on congested venue Wi-Fi, a half-open connection). Such
# a client is dropped after this long, so it can never hold up everyone else.
SEND_TIMEOUT_SECONDS = float(os.environ.get("WS_SEND_TIMEOUT_SECONDS", "1"))

# "Try Again Later": every page reconnects on any close code except 1008, so a
# dropped phone rejoins on its own.
_DROPPED_CLOSE_CODE = 1013

# Strong references to in-flight closes (asyncio only holds weak refs to tasks).
_closing_tasks: set[asyncio.Task] = set()


def participant_ids() -> list[str]:
    """Return sorted UUIDs of non-special connected participants."""
    return sorted(pid for pid in state.participants if pid not in SPECIAL_PIDS)


async def _send(ws: WebSocket, text: str) -> bool:
    """Send within SEND_TIMEOUT_SECONDS; False if the client errored or stalled."""
    try:
        await asyncio.wait_for(ws.send_text(text), SEND_TIMEOUT_SECONDS)
        return True
    except Exception:
        return False


async def _close_quietly(ws: WebSocket) -> None:
    try:
        await ws.close(code=_DROPPED_CLOSE_CODE)
    except Exception:
        pass


def _drop(pid: str, ws: WebSocket) -> None:
    """Forget a failed or stalled socket and close it in the background.

    Removes the entry only while it still maps to THIS socket — the phone may
    already have reconnected under the same id. The close is not awaited: on a
    stalled socket it waits for its own timeout before aborting the connection.
    The socket's connection handler does the rest of the cleanup when it ends.
    """
    if state.participants.get(pid) is ws:
        del state.participants[pid]
    task = asyncio.create_task(_close_quietly(ws))
    _closing_tasks.add(task)
    task.add_done_callback(_closing_tasks.discard)


async def fan_out(text: str, targets: list[tuple[str, WebSocket]]) -> None:
    """Send one message to every (pid, socket) target concurrently.

    A slow client delays the whole fan-out by at most SEND_TIMEOUT_SECONDS, and
    clients that fail or stall are dropped so they cannot stall later fan-outs.
    Each client still gets messages in order as long as the caller awaits one
    fan-out before starting the next (the daemon receive loop does).
    """
    results = await asyncio.gather(*(_send(ws, text) for _, ws in targets))
    for (pid, ws), delivered in zip(targets, results):
        if not delivered:
            _drop(pid, ws)


# App-level heartbeat to participant sockets. WebSocket protocol pings are
# invisible to page JS, so a phone whose connection died silently (a network
# switch while it was in a pocket: no FIN, no RST) never notices and stays on an
# old slide. With a frame at least this often, the talk page can tell and reconnect.
HEARTBEAT_INTERVAL_SECONDS = float(os.environ.get("WS_HEARTBEAT_INTERVAL_SECONDS", "25"))
_HEARTBEAT_FRAME = json.dumps({"type": "heartbeat"})


async def heartbeat_loop() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            targets = [(pid, ws) for pid, ws in state.participants.items() if pid not in SPECIAL_PIDS]
            if targets:
                await fan_out(_HEARTBEAT_FRAME, targets)
        except Exception:
            # Never let the loop die: phones that saw a heartbeat would then all
            # reconnect every minute.
            logger.exception("heartbeat fan-out failed")


async def broadcast(message: Union[BaseModel, dict], exclude: Optional[str] = None):
    """Send identical message to all connected clients."""
    text = message.model_dump_json() if isinstance(message, BaseModel) else json.dumps(message)
    # Snapshot (no await while building it): clients join and leave mid-broadcast.
    await fan_out(text, [(pid, ws) for pid, ws in state.participants.items() if pid != exclude])


async def _broadcast_participant_update_now():
    """Send active (currently connected) participant count update to all connected participants (not host)."""
    count = len([pid for pid in state.participants if pid not in SPECIAL_PIDS])

    msg = json.dumps({
        "type": "active_participants_count_updated",
        "count": count,
    })
    await fan_out(msg, [(pid, ws) for pid, ws in state.participants.items() if pid != "__host__"])


_participant_update_throttle = AsyncThrottle(1.0, _broadcast_participant_update_now)


def broadcast_participant_update():
    """Schedule a throttled participant count broadcast (max 1/sec)."""
    _participant_update_throttle.schedule()
