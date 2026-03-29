"""E2E tests for routers/quiz.py and routers/summary.py."""
import pytest
from conftest import api, pax_url


class TestQuizRequest:
    def test_request_with_minutes(self, server_url):
        resp = api(server_url, "post", "/api/quiz-request", json={"minutes": 30})
        assert resp.status_code == 200

    def test_request_with_topic(self, server_url):
        resp = api(server_url, "post", "/api/quiz-request", json={"topic": "Microservices"})
        assert resp.status_code == 200

    def test_request_neither(self, server_url):
        resp = api(server_url, "post", "/api/quiz-request", json={})
        assert resp.status_code == 422

    def test_request_both(self, server_url):
        resp = api(server_url, "post", "/api/quiz-request", json={"minutes": 30, "topic": "X"})
        assert resp.status_code == 422


class TestQuizPollRequest:
    def test_poll_empty(self, server_url):
        resp = api(server_url, "get", "/api/quiz-request")
        assert resp.status_code == 200
        # request may or may not be None depending on prior tests

    def test_poll_after_request(self, server_url):
        api(server_url, "post", "/api/quiz-request", json={"minutes": 15})
        resp = api(server_url, "get", "/api/quiz-request")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request"] is not None
        assert data["request"]["minutes"] == 15
        # Second poll should return None (consumed)
        resp2 = api(server_url, "get", "/api/quiz-request")
        assert resp2.json()["request"] is None


class TestQuizStatus:
    def test_update_status(self, server_url):
        resp = api(server_url, "post", "/api/quiz-status",
                   json={"status": "generating", "message": "Working..."})
        assert resp.status_code == 200

    def test_update_with_session(self, server_url):
        resp = api(server_url, "post", "/api/quiz-status",
                   json={"status": "idle", "message": "Ready",
                          "session_folder": "/path", "session_notes": "notes.txt"})
        assert resp.status_code == 200


class TestQuizPreview:
    def test_set_preview(self, server_url):
        resp = api(server_url, "post", "/api/quiz-preview",
                   json={"question": "Q?", "options": ["A", "B"], "multi": False, "correct_indices": [0]})
        assert resp.status_code == 200

    def test_clear_preview(self, server_url):
        api(server_url, "post", "/api/quiz-preview",
            json={"question": "Q?", "options": ["A", "B"]})
        resp = api(server_url, "delete", "/api/quiz-preview")
        assert resp.status_code == 200


class TestQuizRefine:
    def test_refine_without_preview(self, server_url):
        api(server_url, "delete", "/api/quiz-preview")
        resp = api(server_url, "post", "/api/quiz-refine", json={"target": "opt0"})
        assert resp.status_code == 400

    def test_refine_with_preview(self, server_url):
        api(server_url, "post", "/api/quiz-preview",
            json={"question": "Q?", "options": ["A", "B"], "correct_indices": [0]})
        resp = api(server_url, "post", "/api/quiz-refine", json={"target": "opt1"})
        assert resp.status_code == 200

    def test_poll_refine(self, server_url):
        resp = api(server_url, "get", "/api/quiz-refine")
        assert resp.status_code == 200


# ── Summary endpoints ─────────────────────────────────────────────────

class TestSummary:
    def test_update_summary(self, server_url):
        resp = api(server_url, "post", "/api/summary",
                   json={"points": [{"text": "Point 1", "source": "discussion", "time": "10:15"}]})
        assert resp.status_code == 200

    def test_get_summary(self, server_url):
        import requests
        resp = requests.get(f"{server_url}{pax_url('/api/summary')}")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data

    def test_update_notes(self, server_url):
        resp = api(server_url, "post", "/api/notes", json={"content": "Session notes here"})
        assert resp.status_code == 200

    def test_get_notes(self, server_url):
        import requests
        resp = requests.get(f"{server_url}{pax_url('/api/notes')}")
        assert resp.status_code == 200
        assert "content" in resp.json()

    def test_transcript_status(self, server_url):
        resp = api(server_url, "post", "/api/transcript-status",
                   json={"line_count": 100, "total_lines": 500, "latest_ts": "10:15:00"})
        assert resp.status_code == 200

    def test_force_summary(self, server_url):
        resp = api(server_url, "post", pax_url("/api/summary/force"))
        assert resp.status_code == 200

    def test_poll_force(self, server_url):
        api(server_url, "post", pax_url("/api/summary/force"))
        resp = api(server_url, "get", "/api/summary/force")
        assert resp.status_code == 200
        assert resp.json()["requested"] is True
        # Second poll should be False
        resp2 = api(server_url, "get", "/api/summary/force")
        assert resp2.json()["requested"] is False
