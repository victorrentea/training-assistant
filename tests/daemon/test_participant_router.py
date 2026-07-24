"""Tests for daemon participant router."""

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.participant.names import get_avatar_filename
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
        resp = client.post(
            "/api/participant/register", json={}, headers={"X-Participant-ID": "uuid1"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"]  # non-empty auto-assigned LOTR name
        assert data["avatar"]  # non-empty
        assert fresh_state.participant_names["uuid1"] == data["name"]

    def test_returning_participant_gets_same_identity(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Bob"
        fresh_state.participant_avatars["uuid1"] = "letter:BO:#abc"
        resp = client.post(
            "/api/participant/register", json={}, headers={"X-Participant-ID": "uuid1"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Bob"
        assert data["avatar"] == "letter:BO:#abc"

    def test_two_participants_get_different_names(self, client, fresh_state):
        resp1 = client.post(
            "/api/participant/register", json={}, headers={"X-Participant-ID": "uuid1"}
        )
        resp2 = client.post(
            "/api/participant/register", json={}, headers={"X-Participant-ID": "uuid2"}
        )
        assert resp1.json()["name"] != resp2.json()["name"]

    def test_conference_mode_auto_assigns_name(self, client, fresh_state):
        fresh_state.mode = "talk"
        resp = client.post(
            "/api/participant/register", json={}, headers={"X-Participant-ID": "uuid1"}
        )
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

    def test_explicit_name_duplicate_is_accepted_with_conflict_flag(self, client, fresh_state):
        """Duplicate names are NEVER blocked: register succeeds with name_conflict=true."""
        fresh_state.participant_names["uuid1"] = "Alice"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"

        resp = client.post(
            "/api/participant/register",
            json={"name": "Alice"},
            headers={"X-Participant-ID": "uuid2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Alice"
        assert data["name_conflict"] is True
        assert fresh_state.participant_names["uuid2"] == "Alice"

    def test_unique_explicit_name_has_no_conflict_flag(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Alice"
        resp = client.post(
            "/api/participant/register",
            json={"name": "Bob"},
            headers={"X-Participant-ID": "uuid2"},
        )
        assert resp.status_code == 200
        assert resp.json()["name_conflict"] is False

    def test_explicit_name_allows_up_to_64_chars(self, client, fresh_state):
        long_name = "A" * 64
        resp = client.post(
            "/api/participant/register",
            json={"name": long_name},
            headers={"X-Participant-ID": "uuid-long"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == long_name
        assert len(fresh_state.participant_names["uuid-long"]) == 64

    def test_returning_participant_register_ignores_new_name(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Persisted Name"
        fresh_state.participant_avatars["uuid1"] = "persisted-avatar.png"

        resp = client.post(
            "/api/participant/register",
            json={"name": "New Name"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Persisted Name"
        assert data["avatar"] == "persisted-avatar.png"

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
        data = resp.json()
        assert data["name"] == "Bob"
        assert data["avatar"] == "letter:BO:#abc"

    def test_rejoin_unknown_uuid_returns_404(self, client, fresh_state):
        resp = client.post("/api/participant/rejoin", headers={"X-Participant-ID": "missing"})
        assert resp.status_code == 404


class TestRename:
    def test_rename_updates_name(self, client, fresh_state):
        # Register first
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client.put(
            "/api/participant/name",
            json={"name": "CustomName"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        assert resp.json()["name_conflict"] is False
        assert fresh_state.participant_names["uuid1"] == "CustomName"

    def test_rename_to_taken_name_is_accepted_with_conflict_flag(self, client, fresh_state):
        """Renaming to a taken name is NEVER blocked (no 409)."""
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_names["uuid2"] = "Alice"
        resp = client.put(
            "/api/participant/name",
            json={"name": "Alice"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        assert resp.json()["name_conflict"] is True
        assert fresh_state.participant_names["uuid1"] == "Alice"

    def test_rename_rejects_unregistered(self, client, fresh_state):
        resp = client.put(
            "/api/participant/name",
            json={"name": "Alice"},
            headers={"X-Participant-ID": "unknown-uuid"},
        )
        assert resp.status_code == 400

    def test_rename_allows_up_to_64_chars(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Gandalf"
        long_name = "A" * 64
        resp = client.put(
            "/api/participant/name", json={"name": long_name}, headers={"X-Participant-ID": "uuid1"}
        )
        assert resp.status_code == 200
        assert fresh_state.participant_names["uuid1"] == long_name
        assert len(fresh_state.participant_names["uuid1"]) == 64

    def test_missing_participant_id_returns_400(self, client):
        resp = client.put("/api/participant/name", json={"name": "Alice"})
        assert resp.status_code == 400


class TestRefreshAvatar:
    def test_refresh_returns_new_avatar(self, client, fresh_state):
        fresh_state.participant_avatars["uuid1"] = "letter:AB:#123"
        resp = client.post(
            "/api/participant/roll-avatar",
            json={"rejected": []},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["avatar"]  # non-empty


class TestSetLocation:
    def test_location_stored(self, client, fresh_state):
        resp = client.put(
            "/api/participant/location",
            json={"location": "Bucharest, Romania"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 204
        assert resp.content == b""
        assert fresh_state.locations["uuid1"] == "Bucharest, Romania"

    def test_empty_location_rejected(self, client, fresh_state):
        resp = client.put(
            "/api/participant/location",
            json={"location": ""},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 400


class TestApplyBrowserTz:
    def test_valid_iana_tz_stored(self, fresh_state):
        from daemon.participant.router import _apply_browser_tz
        assert _apply_browser_tz("uuid1", "Asia/Kolkata") is True
        assert fresh_state.location_timezones["uuid1"] == "Asia/Kolkata"

    def test_invalid_tz_ignored(self, fresh_state):
        from daemon.participant.router import _apply_browser_tz
        assert _apply_browser_tz("uuid1", "Mars/Olympus") is False
        assert "uuid1" not in fresh_state.location_timezones

    def test_blank_tz_ignored(self, fresh_state):
        from daemon.participant.router import _apply_browser_tz
        assert _apply_browser_tz("uuid1", "") is False
        assert _apply_browser_tz("uuid1", None) is False
        assert _apply_browser_tz("uuid1", "   ") is False
        assert "uuid1" not in fresh_state.location_timezones

    def test_unchanged_returns_false(self, fresh_state):
        from daemon.participant.router import _apply_browser_tz
        fresh_state.location_timezones["uuid1"] = "Europe/Bucharest"
        assert _apply_browser_tz("uuid1", "Europe/Bucharest") is False

    def test_overrides_existing_on_change(self, fresh_state):
        from daemon.participant.router import _apply_browser_tz
        fresh_state.location_timezones["uuid1"] = "Europe/Bucharest"
        assert _apply_browser_tz("uuid1", "Asia/Kolkata") is True
        assert fresh_state.location_timezones["uuid1"] == "Asia/Kolkata"


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

    def test_rename_does_not_emit_write_back_events(
        self, client_with_writeback_header, fresh_state
    ):
        fresh_state.participant_names["uuid1"] = "Gandalf"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client_with_writeback_header.put(
            "/api/participant/name",
            json={"name": "CustomName"},
            headers={"X-Participant-ID": "uuid1"},
        )
        assert resp.status_code == 200
        assert "X-Write-Back-Events" not in resp.headers

    def test_roll_avatar_does_not_emit_write_back_events(
        self, client_with_writeback_header, fresh_state
    ):
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


class TestActivity:
    def test_merges_deltas_and_stamps_liveness(self, client, fresh_state):
        resp = client.post(
            "/api/participant/activity",
            json={
                "current_view": "slides",
                "deltas": {"slides": {"seconds": 10, "visits": 1, "clicks": 3}},
            },
            headers={"X-Participant-ID": "u1"},
        )
        assert resp.status_code == 204
        assert fresh_state.engagement["u1"]["slides"] == {
            "seconds": 10,
            "visits": 1,
            "clicks": 3,
        }
        assert fresh_state.last_view["u1"] == "slides"
        assert fresh_state.last_active_at["u1"] > 0

    def test_accumulates_across_reports(self, client, fresh_state):
        client.post(
            "/api/participant/activity",
            json={"current_view": "notes", "deltas": {"notes": {"seconds": 5, "visits": 1, "clicks": 0}}},
            headers={"X-Participant-ID": "u1"},
        )
        client.post(
            "/api/participant/activity",
            json={"current_view": "notes", "deltas": {"notes": {"seconds": 7, "visits": 0, "clicks": 2}}},
            headers={"X-Participant-ID": "u1"},
        )
        assert fresh_state.engagement["u1"]["notes"] == {"seconds": 12, "visits": 1, "clicks": 2}

    def test_missing_participant_id_returns_400(self, client):
        resp = client.post(
            "/api/participant/activity",
            json={"current_view": "slides", "deltas": {}},
        )
        assert resp.status_code == 400

    def test_unknown_view_is_ignored(self, client, fresh_state):
        client.post(
            "/api/participant/activity",
            json={"current_view": "slides", "deltas": {"bogus": {"seconds": 99, "visits": 1, "clicks": 1}}},
            headers={"X-Participant-ID": "u1"},
        )
        assert "bogus" not in fresh_state.engagement.get("u1", {})
