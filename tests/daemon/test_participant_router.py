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


class TestSetName:
    def test_new_participant_gets_name_and_avatar(self, client, fresh_state):
        resp = client.post("/api/participant/name",
                           json={"name": "Alice"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["name"] == "Alice"
        assert data["avatar"]  # non-empty
        assert fresh_state.participant_names["uuid1"] == "Alice"

    def test_returning_participant_fast_path(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Bob"
        fresh_state.participant_avatars["uuid1"] = "letter:BO:#abc"
        resp = client.post("/api/participant/name",
                           json={"name": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["returning"] is True
        assert data["name"] == "Bob"

    def test_duplicate_name_gets_alternative(self, client, fresh_state):
        fresh_state.participant_names["other"] = "Alice"
        resp = client.post("/api/participant/name",
                           json={"name": "Alice"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] != "Alice"  # got an alternative

    def test_empty_name_rejected_in_workshop_mode(self, client, fresh_state):
        resp = client.post("/api/participant/name",
                           json={"name": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_conference_mode_auto_assigns_name(self, client, fresh_state):
        fresh_state.mode = "conference"
        resp = client.post("/api/participant/name",
                           json={"name": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"]  # non-empty auto-assigned name

    def test_debate_late_joiner_auto_assigned(self, client, fresh_state):
        fresh_state.debate_phase = "arguments"
        fresh_state.debate_sides = {"a": "for", "b": "for"}
        resp = client.post("/api/participant/name",
                           json={"name": "Charlie"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert fresh_state.debate_sides["uuid1"] == "against"  # fewer against

    def test_missing_participant_id_returns_400(self, client):
        resp = client.post("/api/participant/name", json={"name": "Alice"})
        assert resp.status_code == 400

    def test_name_truncated_to_32_chars(self, client, fresh_state):
        long_name = "A" * 50
        resp = client.post("/api/participant/name",
                           json={"name": long_name},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert len(fresh_state.participant_names["uuid1"]) <= 32


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
