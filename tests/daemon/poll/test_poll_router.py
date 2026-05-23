"""Tests for daemon poll router — host-only endpoints."""
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def fresh_poll_state():
    from daemon.poll.state import PollState
    ps = PollState()
    with patch("daemon.poll.router.poll_state", ps):
        yield ps


@pytest.fixture
def host_client(fresh_poll_state):
    from daemon.poll.router import host_router
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


_SAMPLE_BODY = {
    "question": "How was lunch?",
    "options": ["Great", "Meh"],
    "multi": False,
    "public": False,
}


def test_router_importable():
    from daemon.poll.router import host_router  # noqa: F401


class TestPollUpdate:
    def test_update_stores_data(self, host_client, fresh_poll_state):
        resp = host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        assert resp.status_code == 204
        assert fresh_poll_state.data is not None
        assert fresh_poll_state.data.question == "How was lunch?"
        assert fresh_poll_state.data.options == ["Great", "Meh"]
        assert fresh_poll_state.data.multi is False

    def test_update_does_not_set_started(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        assert fresh_poll_state.started is False

    def test_update_accepts_incomplete_draft(self, host_client, fresh_poll_state):
        resp = host_client.put("/api/test-session/host/poll/update", json={
            "question": "",
            "options": ["Only one"],
            "multi": False,
            "public": False,
        })
        assert resp.status_code == 204
        assert fresh_poll_state.data.question == ""
        assert fresh_poll_state.data.options == ["Only one"]


class TestPollStart:
    def test_start_with_valid_draft_returns_204(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 204
        assert fresh_poll_state.started is True

    def test_start_with_no_draft_returns_409(self, host_client, fresh_poll_state):
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 409
        assert fresh_poll_state.started is False

    def test_start_with_empty_question_returns_409(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "   ",
            "options": ["A", "B"],
            "multi": False,
            "public": False,
        })
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 409
        assert fresh_poll_state.started is False

    def test_start_with_fewer_than_two_options_returns_409(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "Q?",
            "options": ["only"],
            "multi": False,
            "public": False,
        })
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 409
        assert fresh_poll_state.started is False

    def test_start_ignores_empty_options_when_counting(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "Q?",
            "options": ["A", "", "B"],
            "multi": False,
            "public": False,
        })
        resp = host_client.post("/api/test-session/host/poll/start")
        # Client should never send empty options, but if a draft slipped through with one,
        # the trimmed count must still be >= 2. Here A and B both pass, so accept.
        assert resp.status_code == 204
        assert fresh_poll_state.started is True

    def test_start_is_idempotent(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 204
        assert fresh_poll_state.started is True


class TestPollStop:
    def test_stop_clears_data_and_started(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        assert fresh_poll_state.data is not None
        assert fresh_poll_state.started is True

        resp = host_client.post("/api/test-session/host/poll/stop")
        assert resp.status_code == 204
        assert fresh_poll_state.data is None
        assert fresh_poll_state.started is False

    def test_stop_is_idempotent(self, host_client, fresh_poll_state):
        # No draft, no start — stop should still succeed.
        resp = host_client.post("/api/test-session/host/poll/stop")
        assert resp.status_code == 204
        assert fresh_poll_state.data is None
        assert fresh_poll_state.started is False


@pytest.fixture
def mock_broadcast(monkeypatch):
    """Capture broadcast() calls."""
    calls = []

    def fake_broadcast(msg):
        calls.append(("broadcast", msg.model_dump()))

    monkeypatch.setattr("daemon.poll.router.broadcast", fake_broadcast)
    return calls


@pytest.fixture
def mock_notify_host(monkeypatch):
    calls = []

    async def fake_notify(msg):
        calls.append(("notify_host", msg.model_dump()))

    monkeypatch.setattr("daemon.poll.router.notify_host", fake_notify)
    return calls


@pytest.fixture
def mock_pstate(monkeypatch):
    state = MagicMock()
    state.current_activity = "none"
    monkeypatch.setattr("daemon.poll.router.participant_state", state)
    return state


class TestStartBroadcast:
    def test_start_broadcasts_activity_opened_updated(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 204

        broadcast_types = [m["type"] for ch, m in mock_broadcast if ch == "broadcast"]
        assert "activity_updated" in broadcast_types
        assert "poll_opened" in broadcast_types
        assert "poll_updated" in broadcast_types
        assert mock_pstate.current_activity == "poll"

    def test_start_notifies_host_with_full_counts(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")

        host_msgs = [m for ch, m in mock_notify_host]
        host_types = [m["type"] for m in host_msgs]
        assert "poll_host_update" in host_types
        host_update = next(m for m in host_msgs if m["type"] == "poll_host_update")
        assert host_update["counts"] == [0, 0]
        assert host_update["voted_count"] == 0


class TestUpdateWhileRunning:
    def test_rejects_option_removal_while_running(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        resp = host_client.put("/api/test-session/host/poll/update", json={
            "question": "How was lunch?", "options": ["Great"], "multi": False, "public": False,
        })
        assert resp.status_code == 409

    def test_allows_option_addition_while_running(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        resp = host_client.put("/api/test-session/host/poll/update", json={
            "question": "How was lunch?",
            "options": ["Great", "Meh", "Bad"],
            "multi": False, "public": False,
        })
        assert resp.status_code == 204
        assert fresh_poll_state.data.options == ["Great", "Meh", "Bad"]

    def test_single_to_multi_preserves_votes(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        # _SAMPLE_BODY is single-select. Cast a vote, flip to multi — vote survives.
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        fresh_poll_state.cast_vote("p1", [0])
        assert len(fresh_poll_state.votes) == 1

        host_client.put("/api/test-session/host/poll/update", json={
            "question": "How was lunch?",
            "options": ["Great", "Meh"],
            "multi": True, "public": False,
        })
        assert fresh_poll_state.votes["p1"]["option_indices"] == [0]

    def test_multi_to_single_keeps_single_option_votes_drops_multi(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        # Start in multi mode, two voters: alice picks 1 option, bob picks 2.
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "How was lunch?",
            "options": ["Great", "Meh"],
            "multi": True, "public": False,
        })
        host_client.post("/api/test-session/host/poll/start")
        fresh_poll_state.cast_vote("alice", [0])
        fresh_poll_state.cast_vote("bob", [0, 1])
        assert len(fresh_poll_state.votes) == 2

        # Flip to single: alice's [0] kept, bob's [0,1] dropped.
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "How was lunch?",
            "options": ["Great", "Meh"],
            "multi": False, "public": False,
        })
        assert "alice" in fresh_poll_state.votes
        assert "bob" not in fresh_poll_state.votes
        assert fresh_poll_state.votes["alice"]["option_indices"] == [0]


class TestStopBroadcast:
    def test_stop_broadcasts_activity_none(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        mock_pstate.current_activity = "poll"
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        host_client.post("/api/test-session/host/poll/stop")

        broadcast_types = [m["type"] for ch, m in mock_broadcast if ch == "broadcast"]
        assert "activity_updated" in broadcast_types
        activity_msgs = [m for ch, m in mock_broadcast if ch == "broadcast" and m["type"] == "activity_updated"]
        assert activity_msgs[-1]["current_activity"] == "none"


@pytest.fixture
def participant_client(fresh_poll_state):
    from daemon.poll.router import participant_router
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


class TestPollVote:
    def test_vote_when_active_returns_204(
        self, host_client, participant_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")

        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [0]},
            headers={"x-participant-id": "alice"},
        )
        assert resp.status_code == 204
        assert fresh_poll_state.votes["alice"]["option_indices"] == [0]

    def test_vote_missing_pid_returns_400(self, participant_client, fresh_poll_state):
        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [0]},
        )
        assert resp.status_code == 400

    def test_vote_when_not_started_returns_409(self, participant_client, fresh_poll_state):
        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [0]},
            headers={"x-participant-id": "alice"},
        )
        assert resp.status_code == 409

    def test_vote_out_of_range_returns_409(
        self, host_client, participant_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")

        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [99]},
            headers={"x-participant-id": "alice"},
        )
        assert resp.status_code == 409

    def test_vote_broadcasts_when_public(
        self, host_client, participant_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "Q?", "options": ["A", "B"], "multi": False, "public": True,
        })
        host_client.post("/api/test-session/host/poll/start")
        mock_broadcast.clear()

        participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [1]},
            headers={"x-participant-id": "alice"},
        )

        broadcast_updates = [m for ch, m in mock_broadcast if ch == "broadcast" and m["type"] == "poll_updated"]
        assert len(broadcast_updates) == 1
        assert broadcast_updates[0]["counts"] == [0, 1]

    def test_vote_does_not_broadcast_counts_when_private(
        self, host_client, participant_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "Q?", "options": ["A", "B"], "multi": False, "public": False,
        })
        host_client.post("/api/test-session/host/poll/start")
        mock_broadcast.clear()

        participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [1]},
            headers={"x-participant-id": "alice"},
        )

        broadcast_updates = [m for ch, m in mock_broadcast if ch == "broadcast" and m["type"] == "poll_updated"]
        for u in broadcast_updates:
            assert u["counts"] is None


class TestHostGetPoll:
    def test_returns_null_when_no_data(self, host_client, fresh_poll_state):
        resp = host_client.get("/api/test-session/host/poll")
        assert resp.status_code == 200
        assert resp.json() == {"poll": None, "started": False, "counts": [], "voted_count": 0}

    def test_returns_snapshot_when_running(
        self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host, mock_pstate
    ):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        fresh_poll_state.cast_vote("alice", [0])

        resp = host_client.get("/api/test-session/host/poll")
        data = resp.json()
        assert data["started"] is True
        assert data["counts"] == [1, 0]
        assert data["voted_count"] == 1
        assert data["poll"]["question"] == "How was lunch?"
