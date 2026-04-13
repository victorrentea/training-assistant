from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from railway.features.ws import router as ws_router
from railway.shared.state import state


@pytest.fixture(autouse=True)
def clean_state():
    state.reset()
    state.generate_session_id()
    yield
    state.reset()


@pytest.mark.anyio
async def test_participant_registered_write_back_updates_state_and_broadcasts():
    with patch("railway.features.ws.router.broadcast_participant_update", new=MagicMock()) as broadcast_mock:
        await ws_router._handle_participant_registered(
            {
                "type": "participant_registered",
                "participant_id": "uuid-1",
                "name": "Alice",
                "avatar": "gandalf.png",
                "score": 5,
                "universe": "lotr",
            }
        )

    assert state.participant_names["uuid-1"] == "Alice"
    assert state.participant_avatars["uuid-1"] == "gandalf.png"
    assert state.scores["uuid-1"] == 5
    broadcast_mock.assert_called_once()


@pytest.mark.anyio
async def test_participant_registered_ignores_invalid_id():
    with patch("railway.features.ws.router.broadcast_participant_update", new=MagicMock()) as broadcast_mock:
        await ws_router._handle_participant_registered(
            {
                "type": "participant_registered",
                "participant_id": "__host__",
                "name": "Host",
            }
        )

    assert "__host__" not in state.participant_names
    broadcast_mock.assert_not_called()
