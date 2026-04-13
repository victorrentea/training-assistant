"""Tests for daemon participant router."""
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.participant.router import router
from daemon.participant.state import ParticipantState
from railway.shared.state import get_avatar_filename


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


@pytest.fixture
def client_with_writeback_header(fresh_state):
    """TestClient that mirrors host_server write-back header behavior."""
    app = FastAPI()

    @app.middleware("http")
    async def write_back_middleware(request, call_next):
        request.state.write_back_events = []
        response = await call_next(request)
        events = getattr(request.state, "write_back_events", [])
        if events:
            response.headers["X-Write-Back-Events"] = json.dumps(events)
        return response

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

    def test_new_participant_can_register_with_explicit_name(self, client, fresh_state):
        resp = client.post(
            "/api/participant/register",
            json={"name": "Alice"},
            headers={"X-Participant-ID": "uuid-explicit"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Alice"
        assert data["avatar"]
        assert fresh_state.participant_names["uuid-explicit"] == "Alice"

    def test_explicit_name_duplicate_returns_409(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Alice"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"

        resp = client.post(
            "/api/participant/register",
            json={"name": "Alice"},
            headers={"X-Participant-ID": "uuid2"},
        )
        assert resp.status_code == 409

    def test_returning_participant_register_ignores_new_name(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Persisted Name"
        fresh_state.participant_avatars["uuid1"] = "persisted-avatar.png"

        resp = client.post(
            "/api/participant/register",
            json={"name": "New Name"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"name": "Persisted Name", "avatar": "persisted-avatar.png"}

    def test_explicit_name_gets_available_avatar_not_used_by_others(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"

        resp = client.post(
            "/api/participant/register",
            json={"name": "Alice"},
            headers={"X-Participant-ID": "uuid2"},
        )
        assert resp.status_code == 200
        assert resp.json()["avatar"] != "gandalf.png"

    def test_random_register_keeps_name_avatar_in_sync_when_available(self, client, fresh_state):
        resp = client.post(
            "/api/participant/register",
            json={},
            headers={"X-Participant-ID": "uuid-random"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["avatar"] == get_avatar_filename(data["name"])


class TestRejoin:
    def test_rejoin_returns_existing_identity(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Bob"
        fresh_state.participant_avatars["uuid1"] = "letter:BO:#abc"

        resp = client.post("/api/participant/rejoin", headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert resp.json() == {"name": "Bob", "avatar": "letter:BO:#abc"}

    def test_rejoin_unknown_uuid_returns_404(self, client, fresh_state):
        resp = client.post("/api/participant/rejoin", headers={"X-Participant-ID": "missing"})
        assert resp.status_code == 404


class TestRename:
    def test_rename_updates_name(self, client, fresh_state):
        # Register first
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client.put("/api/participant/name",
                          json={"name": "CustomName"},
                          headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 204
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
        assert resp.status_code == 204
        assert len(fresh_state.participant_names["uuid1"]) <= 32

    def test_missing_participant_id_returns_400(self, client):
        resp = client.put("/api/participant/name", json={"name": "Alice"})
        assert resp.status_code == 400


class TestRefreshAvatar:
    def test_refresh_returns_new_avatar(self, client, fresh_state):
        fresh_state.participant_avatars["uuid1"] = "letter:AB:#123"
        resp = client.post("/api/participant/roll-avatar",
                           json={"rejected": []},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["avatar"]  # non-empty


class TestSetLocation:
    def test_location_stored(self, client, fresh_state):
        resp = client.put("/api/participant/location",
                          json={"location": "Bucharest, Romania"},
                          headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 204
        assert resp.content == b""
        assert fresh_state.locations["uuid1"] == "Bucharest, Romania"

    def test_empty_location_rejected(self, client, fresh_state):
        resp = client.put("/api/participant/location",
                          json={"location": ""},
                          headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400


class TestParticipantState:
    def test_state_does_not_include_participant_count(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Alice"

        resp = client.get("/api/participant/state", headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert "participant_count" not in resp.json()

    def test_state_includes_slides_history_count(self, client, fresh_state):
        from daemon.misc.state import misc_state

        old_slides_viewed = list(misc_state.slides_viewed)
        misc_state.slides_viewed = [
            {"file_name": "AI.pptx", "page": 3, "seconds": 120},
            {"file_name": "AI.pptx", "page": 4, "seconds": 30},
        ]
        try:
            resp = client.get("/api/participant/state", headers={"X-Participant-ID": "uuid1"})
            assert resp.status_code == 200
            assert resp.json()["slides_history_count"] == 2
        finally:
            misc_state.slides_viewed = old_slides_viewed


class TestNoParticipantWriteBackEvents:
    def test_register_does_not_emit_write_back_events(self, client_with_writeback_header):
        resp = client_with_writeback_header.post(
            "/api/participant/register",
            json={},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        assert "X-Write-Back-Events" not in resp.headers

    def test_rename_does_not_emit_write_back_events(self, client_with_writeback_header, fresh_state):
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client_with_writeback_header.put(
            "/api/participant/name",
            json={"name": "CustomName"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 204
        assert "X-Write-Back-Events" not in resp.headers

    def test_roll_avatar_does_not_emit_write_back_events(self, client_with_writeback_header, fresh_state):
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client_with_writeback_header.post(
            "/api/participant/roll-avatar",
            json={"rejected": []},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        assert "X-Write-Back-Events" not in resp.headers

    def test_location_does_not_emit_write_back_events(self, client_with_writeback_header):
        resp = client_with_writeback_header.put(
            "/api/participant/location",
            json={"location": "Bucharest, Romania"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 204
        assert "X-Write-Back-Events" not in resp.headers
