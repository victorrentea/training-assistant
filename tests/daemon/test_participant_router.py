"""Tests for daemon participant router."""
import pytest
from unittest.mock import patch
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.participant.router import router
from daemon.participant.state import ParticipantState


@pytest.fixture
def fresh_state():
    """Provide a clean ParticipantState for each test."""
    ps = ParticipantState()
    ps.mode = "workshop"
    with patch("daemon.participant.router.participant_state", ps):
        yield ps


@pytest.fixture
def client(fresh_state):
    """TestClient with participant router mounted."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRegister:
    def test_new_participant_gets_name_and_avatar(self, client, fresh_state):
        resp = client.post("/api/participant/register",
                           json={},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"]  # non-empty auto-assigned LOTR name
        assert data["avatar"]  # non-empty
        assert fresh_state.participant_names["uuid1"] == data["name"]

    def test_returning_participant_gets_same_identity(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Bob"
        fresh_state.participant_avatars["uuid1"] = "letter:BO:#abc"
        resp = client.post("/api/participant/register",
                           json={},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Bob"
        assert data["avatar"] == "letter:BO:#abc"

    def test_two_participants_get_different_names(self, client, fresh_state):
        resp1 = client.post("/api/participant/register", json={},
                            headers={"X-Participant-ID": "uuid1"})
        resp2 = client.post("/api/participant/register", json={},
                            headers={"X-Participant-ID": "uuid2"})
        assert resp1.json()["name"] != resp2.json()["name"]

    def test_conference_mode_auto_assigns_name(self, client, fresh_state):
        fresh_state.mode = "conference"
        resp = client.post("/api/participant/register",
                           json={},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert resp.json()["name"]  # non-empty auto-assigned name

    def test_missing_participant_id_returns_400(self, client):
        resp = client.post("/api/participant/register", json={})
        assert resp.status_code == 400


class TestRename:
    def test_rename_updates_name(self, client, fresh_state):
        # Register first
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client.put("/api/participant/name",
                          json={"name": "CustomName"},
                          headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert fresh_state.participant_names["uuid1"] == "CustomName"

    def test_rename_rejects_unregistered(self, client, fresh_state):
        resp = client.put("/api/participant/name",
                          json={"name": "Alice"},
                          headers={"X-Participant-ID": "unknown-uuid"})
        assert resp.status_code == 400

    def test_rename_truncated_to_32_chars(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Gandalf"
        long_name = "A" * 50
        resp = client.put("/api/participant/name",
                          json={"name": long_name},
                          headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert len(fresh_state.participant_names["uuid1"]) <= 32

    def test_missing_participant_id_returns_400(self, client):
        resp = client.put("/api/participant/name", json={"name": "Alice"})
        assert resp.status_code == 400


class TestRefreshAvatar:
    def test_refresh_returns_new_avatar(self, client, fresh_state):
        fresh_state.participant_avatars["uuid1"] = "letter:AB:#123"
        resp = client.post("/api/participant/avatar",
                           json={"rejected": []},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["avatar"]  # non-empty


class TestSetLocation:
    def test_location_stored(self, client, fresh_state):
        resp = client.post("/api/participant/location",
                           json={"location": "Bucharest, Romania"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert fresh_state.locations["uuid1"] == "Bucharest, Romania"

    def test_empty_location_rejected(self, client, fresh_state):
        resp = client.post("/api/participant/location",
                           json={"location": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400


class TestParticipantState:
    def test_state_uses_session_stack_name_fallback(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Alice"
        with patch("daemon.misc.state.misc_state.session_name", None):
            with patch(
                "daemon.participant.router.session_shared_state.get_session_stack",
                return_value=[{"name": "2026-04-06 Productive Session"}],
            ):
                resp = client.get("/api/participant/state", headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert resp.json()["session_name"] == "2026-04-06 Productive Session"
