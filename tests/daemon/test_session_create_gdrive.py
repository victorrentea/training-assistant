"""Tests for GDrive precondition on POST /api/session/create and /api/session/resume."""
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.session.router import global_router


def _client():
    app = FastAPI()
    app.include_router(global_router)
    return TestClient(app, raise_server_exceptions=False)


# ── PersistedSessionState ────────────────────────────────────────────────────
# gdrive_url is no longer persisted: live-resolved each session start/resume to
# avoid stale-URL leakage when a session is resumed via the landing page.

class TestPersistedSessionStateGdriveUrl:
    def test_legacy_state_with_gdrive_url_still_loads(self):
        """Legacy session-state.json files with gdrive_url must still load (read tolerant)."""
        from daemon.persisted_models import PersistedSessionState

        state = PersistedSessionState.model_validate({
            "session_id": "abc123",
            "gdrive_url": "https://drive.google.com/drive/folders/FOLDER_ID",
        })
        assert state.gdrive_url == "https://drive.google.com/drive/folders/FOLDER_ID"

    def test_gdrive_url_excluded_from_dump(self):
        """gdrive_url must never be re-emitted on write — it's live-resolved only."""
        from daemon.persisted_models import PersistedSessionState

        state = PersistedSessionState.model_validate({
            "session_id": "abc123",
            "gdrive_url": "https://drive.google.com/drive/folders/FOLDER_ID",
        })
        dumped = state.model_dump(mode="json")
        assert "gdrive_url" not in dumped

    def test_state_without_gdrive_url_loads_as_none(self):
        from daemon.persisted_models import PersistedSessionState

        state = PersistedSessionState.model_validate({"session_id": "abc123"})
        assert state.gdrive_url is None


# ── POST /api/session/create — 503 when GDrive unavailable ────────────────────

class TestSessionCreateGdrive:
    def test_returns_503_when_gdrive_unavailable(self, tmp_path):
        """Session create must return 503 with gdrive_unavailable error if GDrive is offline."""
        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._GDRIVE_WAIT_TIMEOUT_S", 0.0), \
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
        # Folder must be pre-created so DriveFS can sync it back to Google Drive.
        assert (tmp_path / "2026-05-22 My Workshop").is_dir()

    def test_503_does_not_create_session(self, tmp_path):
        """On GDrive 503, no session request must be queued."""
        put_calls = []

        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._GDRIVE_WAIT_TIMEOUT_S", 0.0), \
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

    def test_waits_for_gdrive_then_succeeds(self, tmp_path):
        """If DriveFS becomes ready mid-wait, the endpoint returns the resolved URL."""
        gdrive_url = "https://drive.google.com/drive/folders/LATE"
        call_count = {"n": 0}

        def slow_resolve(_folder):
            call_count["n"] += 1
            return gdrive_url if call_count["n"] >= 3 else None

        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._GDRIVE_WAIT_TIMEOUT_S", 5.0), \
             patch("daemon.session.router._GDRIVE_POLL_INTERVAL_S", 0.01), \
             patch("daemon.session.router._resolve_gdrive_url_fn", side_effect=slow_resolve), \
             patch("daemon.session.router.session_pending.put"), \
             patch("daemon.session.router.announce_session_id"):
            resp = _client().post(
                "/api/session/create",
                json={"name": "2026-05-22 Late Workshop", "type": "talk"},
            )

        assert resp.status_code == 200
        assert call_count["n"] >= 3


# ── POST /api/session/resume — same GDrive precondition as /create ────────────

class TestSessionResumeGdrive:
    """Resume must re-resolve gdrive_url so a stale URL from the previous session
    never leaks into the new session's view (the original bug: a previous client's URL showed
    up on the next session's participant page after resuming via the landing card).
    """

    def test_returns_503_when_gdrive_unavailable(self, tmp_path):
        folder = tmp_path / "2026-05-22 My Workshop"
        folder.mkdir()
        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._GDRIVE_WAIT_TIMEOUT_S", 0.0), \
             patch("daemon.session.router._resolve_gdrive_url_fn", return_value=None):
            resp = _client().post(
                "/api/session/resume",
                json={"folder": "2026-05-22 My Workshop"},
            )
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "gdrive_unavailable"

    def test_resume_queues_request_with_fresh_gdrive_url(self, tmp_path):
        """Resume must put the FRESHLY-resolved gdrive_url on the queue (not None)."""
        folder = tmp_path / "2026-05-22 My Workshop"
        folder.mkdir()
        gdrive_url = "https://drive.google.com/drive/folders/FRESH"
        queued = {}

        def fake_put(key, value):
            queued.update(value)

        with patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router._resolve_gdrive_url_fn", return_value=gdrive_url), \
             patch("daemon.session.router.session_pending.put", side_effect=fake_put), \
             patch("daemon.session.router.announce_session_id"):
            resp = _client().post(
                "/api/session/resume",
                json={"folder": "2026-05-22 My Workshop"},
            )

        assert resp.status_code == 200
        assert queued.get("gdrive_url") == gdrive_url
        assert queued.get("action") == "create"
        assert queued.get("existed") is True
