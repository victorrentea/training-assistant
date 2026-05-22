"""Tests for GDrive precondition on POST /api/session/create."""
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.session.router import global_router


def _client():
    app = FastAPI()
    app.include_router(global_router)
    return TestClient(app, raise_server_exceptions=False)


# ── PersistedSessionState round-trip ─────────────────────────────────────────

class TestPersistedSessionStateGdriveUrl:
    def test_round_trip_with_gdrive_url_set(self):
        from daemon.persisted_models import PersistedSessionState

        state = PersistedSessionState.model_validate({
            "session_id": "abc123",
            "gdrive_url": "https://drive.google.com/drive/folders/FOLDER_ID",
        })
        assert state.gdrive_url == "https://drive.google.com/drive/folders/FOLDER_ID"
        dumped = state.model_dump(mode="json")
        assert dumped["gdrive_url"] == "https://drive.google.com/drive/folders/FOLDER_ID"

    def test_round_trip_with_gdrive_url_absent(self):
        from daemon.persisted_models import PersistedSessionState

        state = PersistedSessionState.model_validate({"session_id": "abc123"})
        assert state.gdrive_url is None

    def test_legacy_state_without_gdrive_url_loads_as_none(self):
        """Older session-state.json files without gdrive_url must still load."""
        from daemon.persisted_models import PersistedSessionState

        state = PersistedSessionState.model_validate({
            "session_id": "old123",
            "mode": "workshop",
            "current_activity": "none",
        })
        assert state.gdrive_url is None


# ── POST /api/session/create — 503 when GDrive unavailable ────────────────────

class TestSessionCreateGdrive:
    def test_returns_503_when_gdrive_unavailable(self, tmp_path):
        """Session create must return 503 with gdrive_unavailable error if GDrive is offline."""
        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._resolve_gdrive_url_fn", return_value=None):
            resp = _client().post(
                "/api/session/create",
                json={"name": "2026-05-22 My Workshop", "type": "workshop"},
            )
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "gdrive_unavailable"
        assert "Google Drive" in data["message"]

    def test_returns_200_and_queues_request_when_gdrive_available(self, tmp_path):
        """Happy path: gdrive_url is resolved, session request is queued, URL not in response."""
        gdrive_url = "https://drive.google.com/drive/folders/FOLDER"
        queued = {}

        def fake_put(key, value):
            queued.update(value)

        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._resolve_gdrive_url_fn", return_value=gdrive_url), \
             patch("daemon.session.router.session_pending.put", side_effect=fake_put), \
             patch("daemon.session.router.announce_session_id"):
            resp = _client().post(
                "/api/session/create",
                json={"name": "2026-05-22 My Workshop", "type": "workshop"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_name"] == "2026-05-22 My Workshop"
        assert data["session_id"]
        assert queued.get("gdrive_url") == gdrive_url

    def test_503_does_not_create_session(self, tmp_path):
        """On GDrive 503, no session request must be queued."""
        put_calls = []

        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._resolve_gdrive_url_fn", return_value=None), \
             patch("daemon.session.router.session_pending.put", side_effect=put_calls.append), \
             patch("daemon.session.router.announce_session_id") as mock_announce:
            resp = _client().post(
                "/api/session/create",
                json={"name": "2026-05-22 Workshop", "type": "workshop"},
            )

        assert resp.status_code == 503
        assert len(put_calls) == 0
        mock_announce.assert_not_called()
