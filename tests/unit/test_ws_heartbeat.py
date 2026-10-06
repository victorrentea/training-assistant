"""The relay sends an app-level heartbeat to participant sockets (not the host), so a
talk page can detect a connection that died silently and reconnect."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

import railway.shared.messaging as messaging
from railway.shared.state import state


@pytest.fixture(autouse=True)
def clean_state():
    state.reset()
    yield
    state.reset()


def test_heartbeat_goes_to_participants_not_the_host(monkeypatch):
    monkeypatch.setattr(messaging, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    phone, host = AsyncMock(), AsyncMock()
    state.participants["phone-1"] = phone
    state.participants["__host__"] = host

    async def run():
        task = asyncio.create_task(messaging.heartbeat_loop())
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    assert phone.send_text.await_count >= 1
    assert json.loads(phone.send_text.await_args.args[0]) == {"type": "heartbeat"}
    host.send_text.assert_not_awaited()
