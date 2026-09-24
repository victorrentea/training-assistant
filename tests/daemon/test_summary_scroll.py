"""The host's reading position in the summary, relayed so participants can follow it."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc import router as misc_router
from daemon.misc.state import misc_state
from daemon.ws_messages import SummaryScrollMsg


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(misc_router.local_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_position():
    misc_state.summary_scroll = None
    yield
    misc_state.summary_scroll = None


POSITION = {
    "block_key": "1x9k3.1",
    "path": [2, 0],
    "within": 0.25,
    "summary_updated_at": "2026-09-24T16:30:00+00:00",
}


def test_host_scroll_is_broadcast_to_participants():
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _client().post("/summary/scroll", json=POSITION)

    assert resp.status_code == 200
    msg = broadcast.call_args.args[0]
    assert isinstance(msg, SummaryScrollMsg)
    assert msg.model_dump() == {"type": "summary_scroll", **POSITION}


def test_latest_position_is_kept_for_participants_who_join_later():
    with patch.object(misc_router, "broadcast"):
        _client().post("/summary/scroll", json=POSITION)
        _client().post("/summary/scroll", json={**POSITION, "path": [3]})

    assert misc_state.summary_scroll["path"] == [3]


def test_new_session_forgets_the_old_position():
    misc_state.summary_scroll = dict(POSITION)
    misc_state.reset_for_new_session()
    assert misc_state.summary_scroll is None


@pytest.mark.parametrize("bad", [
    {"within": 1.5},
    {"within": -0.1},
    {"path": list(range(50))},
    {"path": [-1]},
    {"summary_updated_at": "x" * 200},
    {"block_key": "x" * 200},
    {"block_key": ""},
])
def test_malformed_position_is_rejected_before_it_reaches_every_screen(bad):
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _client().post("/summary/scroll", json={**POSITION, **bad})

    assert resp.status_code == 422
    broadcast.assert_not_called()
    assert misc_state.summary_scroll is None
