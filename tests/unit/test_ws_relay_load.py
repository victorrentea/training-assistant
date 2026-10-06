"""Gateway broadcasts and participant-socket lifecycle under conference load.

Covers the relay fixes for a 400-500 phone talk:
- Railway's own broadcasts iterate a snapshot, so joins/leaves mid-broadcast
  cannot raise "dictionary changed size during iteration";
- a dropped or late-disconnecting socket never evicts a newer socket that the
  same participant id reconnected with, and any error still cleans up.

Sockets are in-process fakes, so the assertions are deterministic.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY
from starlette.websockets import WebSocketDisconnect

import railway.shared.messaging as messaging
from railway.features.ws import router as ws_router
from railway.features.ws.router import _handle_participant_connection, _kick_old_connection
from railway.shared.messaging import broadcast
from railway.shared.state import state

pytestmark = pytest.mark.anyio


class FakeSocket:
    """Stands in for a Starlette WebSocket and records what the gateway sends it."""

    def __init__(self, *, stall: bool = False, delay: float = 0.0):
        self.stall = stall  # a phone that stopped reading: its send never completes
        self.delay = delay
        self.sent: list[str] = []
        self.sent_at: list[float] = []
        self.close_codes: list[int] = []
        self.headers: dict = {}
        self.query_params: dict = {}
        self.client = None
        self._inbox: asyncio.Queue = asyncio.Queue()

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        if self.stall:
            await asyncio.Event().wait()
        await asyncio.sleep(self.delay)
        self.sent.append(text)
        self.sent_at.append(asyncio.get_running_loop().time())

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)

    async def receive_text(self) -> str:
        item = await self._inbox.get()
        if isinstance(item, BaseException):
            raise item
        return item

    def disconnect(self, exc: BaseException | None = None) -> None:
        """Make the pending receive_text() end the connection."""
        self._inbox.put_nowait(exc or WebSocketDisconnect(code=1006))


@pytest.fixture(autouse=True)
def _clean_state():
    state.reset()
    state.session_id = "sess01"
    yield
    state.reset()


def _failing_socket() -> FakeSocket:
    ws = FakeSocket()
    ws.send_text = AsyncMock(side_effect=RuntimeError("connection reset"))
    return ws


# ---------------------------------------------------------------------------
# Railway's own broadcasts
# ---------------------------------------------------------------------------

async def test_broadcast_survives_joins_and_leaves_mid_broadcast():
    joiner = FakeSocket()
    leaver = FakeSocket()
    bystander = FakeSocket()
    mutator = FakeSocket()

    async def _send_while_others_come_and_go(text):
        await asyncio.sleep(0)
        state.participants["joiner"] = joiner
        state.participants.pop("leaver", None)
        mutator.sent.append(text)

    mutator.send_text = _send_while_others_come_and_go
    state.participants = {"mutator": mutator, "leaver": leaver, "bystander": bystander}

    await broadcast({"type": "decks_updated"})

    assert mutator.sent and bystander.sent, "broadcast aborted part-way"
    assert joiner.sent == []  # joined after the snapshot
    assert set(state.participants) == {"mutator", "bystander", "joiner"}


async def test_a_failing_send_drops_only_that_client():
    good = FakeSocket()
    bad = _failing_socket()
    state.participants = {"good": good, "bad": bad}

    await broadcast({"type": "decks_updated"})

    assert good.sent and "good" in state.participants
    assert "bad" not in state.participants


async def test_drop_spares_the_socket_the_phone_reconnected_with():
    """The phone reconnects while its old socket's send is failing: the drop must
    not evict the new socket registered under the same participant id."""
    reconnected = FakeSocket()
    stale = FakeSocket()

    async def _fail_after_reconnect(text):
        state.participants["phone"] = reconnected
        raise RuntimeError("connection reset")

    stale.send_text = _fail_after_reconnect
    state.participants = {"phone": stale}

    await broadcast({"type": "emoji_counters_updated", "counters": {}})

    assert state.participants["phone"] is reconnected


async def test_participant_count_update_skips_the_host():
    phone = FakeSocket()
    host = FakeSocket()
    state.participants = {"phone": phone, "__host__": host}

    await messaging._broadcast_participant_update_now()

    assert json.loads(phone.sent[0]) == {"type": "active_participants_count_updated", "count": 1}
    assert host.sent == []


# ---------------------------------------------------------------------------
# Participant socket lifecycle: duplicate ids and cleanup
# ---------------------------------------------------------------------------

@pytest.fixture
def daemon_push(monkeypatch):
    push = AsyncMock(return_value=True)
    monkeypatch.setattr(ws_router, "push_to_daemon", push)
    monkeypatch.setattr(ws_router, "broadcast_participant_update", MagicMock())
    return push


def _offline_pushes(push: AsyncMock, pid: str) -> int:
    return sum(
        1 for call in push.await_args_list
        if call.args[0] == {"type": "participant_presence", "uuid": pid, "online": False}
    )


def _open_participant_sockets() -> float:
    return REGISTRY.get_sample_value("ws_connections_active", {"role": "participant"}) or 0.0


async def _connect(ws: FakeSocket, pid: str, is_host: bool = False) -> asyncio.Task:
    task = asyncio.create_task(_handle_participant_connection(ws, pid, is_host=is_host))
    for _ in range(50):
        if state.participants.get(pid) is ws:
            return task
        await asyncio.sleep(0)
    raise AssertionError(f"{pid} never registered")


async def test_late_disconnect_of_a_replaced_socket_keeps_the_new_one(daemon_push):
    """A phone reconnects before its old socket's disconnect is detected: the late
    disconnect must not remove the new live socket nor report the phone offline."""
    old, new = FakeSocket(), FakeSocket()
    old_task = await _connect(old, "phone")
    new_task = await _connect(new, "phone")

    old.disconnect()
    await old_task

    assert state.participants.get("phone") is new
    assert _offline_pushes(daemon_push, "phone") == 0

    new.disconnect()
    await new_task

    assert "phone" not in state.participants
    assert _offline_pushes(daemon_push, "phone") == 1


async def test_a_socket_dropped_by_a_broadcast_reports_offline_when_it_ends(daemon_push):
    ws = FakeSocket()
    task = await _connect(ws, "phone")
    ws.send_text = AsyncMock(side_effect=RuntimeError("connection reset"))

    await broadcast({"type": "decks_updated"})  # drops it
    assert "phone" not in state.participants

    ws.disconnect()
    await task
    assert _offline_pushes(daemon_push, "phone") == 1


async def test_an_unexpected_error_still_cleans_up(daemon_push):
    """Not just WebSocketDisconnect: any error must release the entry and gauge."""
    before = _open_participant_sockets()
    ws = FakeSocket()
    task = await _connect(ws, "phone")
    assert _open_participant_sockets() == before + 1

    ws.disconnect(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await task

    assert "phone" not in state.participants
    assert "phone" not in state.participant_ips
    assert _open_participant_sockets() == before
    assert _offline_pushes(daemon_push, "phone") == 1


async def test_host_kick_spares_a_host_socket_registered_meanwhile():
    old_host = FakeSocket()
    newer_host = FakeSocket()

    async def _close_while_a_newer_host_registers(code=1000):
        old_host.close_codes.append(code)
        state.participants["__host__"] = newer_host

    old_host.close = _close_while_a_newer_host_registers
    state.participants = {"__host__": old_host}

    await _kick_old_connection("__host__")

    assert old_host.close_codes == [1001]
    assert state.participants["__host__"] is newer_host
