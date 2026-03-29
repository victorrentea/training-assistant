"""E2E tests for routers/quiz.py and routers/summary.py."""
import pytest
from conftest import api, sapi, papi


class TestQuizRequest:
    def test_request_with_minutes(self, server_url):
        resp = sapi(server_url, "post", "/quiz-request", json={"minutes": 30})
        assert resp.status_code == 200

    def test_request_with_topic(self, server_url):
        resp = sapi(server_url, "post", "/quiz-request", json={"topic": "Microservices"})
        assert resp.status_code == 200

    def test_request_neither(self, server_url):
        resp = sapi(server_url, "post", "/quiz-request", json={})
        assert resp.status_code == 422

    def test_request_both(self, server_url):
        resp = sapi(server_url, "post", "/quiz-request", json={"minutes": 30, "topic": "X"})
        assert resp.status_code == 422


class TestQuizPollRequest:
    def test_poll_empty(self, server_url):
        resp = sapi(server_url, "get", "/quiz-request")
        assert resp.status_code == 200
        # request may or may not be None depending on prior tests

    def test_poll_after_request(self, server_url):
        sapi(server_url, "post", "/quiz-request", json={"minutes": 15})
        resp = sapi(server_url, "get", "/quiz-request")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request"] is not None
        assert data["request"]["minutes"] == 15
        # Second poll should return None (consumed)
        resp2 = sapi(server_url, "get", "/quiz-request")
        assert resp2.json()["request"] is None


class TestQuizStatus:
    def test_update_status(self, server_url):
        resp = sapi(server_url, "post", "/quiz-status",
                   json={"status": "generating", "message": "Working..."})
        assert resp.status_code == 200

    def test_update_with_session(self, server_url):
        resp = sapi(server_url, "post", "/quiz-status",
                   json={"status": "idle", "message": "Ready",
                          "session_folder": "/path", "session_notes": "notes.txt"})
        assert resp.status_code == 200


class TestQuizPreview:
    def test_set_preview(self, server_url):
        resp = sapi(server_url, "post", "/quiz-preview",
                   json={"question": "Q?", "options": ["A", "B"], "multi": False, "correct_indices": [0]})
        assert resp.status_code == 200

    def test_clear_preview(self, server_url):
        sapi(server_url, "post", "/quiz-preview",
            json={"question": "Q?", "options": ["A", "B"]})
        resp = sapi(server_url, "delete", "/quiz-preview")
        assert resp.status_code == 200


class TestQuizRefine:
    def test_refine_without_preview(self, server_url):
        sapi(server_url, "delete", "/quiz-preview")
        resp = sapi(server_url, "post", "/quiz-refine", json={"target": "opt0"})
        assert resp.status_code == 400

    def test_refine_with_preview(self, server_url):
        sapi(server_url, "post", "/quiz-preview",
            json={"question": "Q?", "options": ["A", "B"], "correct_indices": [0]})
        resp = sapi(server_url, "post", "/quiz-refine", json={"target": "opt1"})
        assert resp.status_code == 200

    def test_poll_refine(self, server_url):
        resp = sapi(server_url, "get", "/quiz-refine")
        assert resp.status_code == 200


# ── Summary endpoints ─────────────────────────────────────────────────

class TestSummary:
    def test_update_summary(self, server_url):
        resp = sapi(server_url, "post", "/summary",
                   json={"points": [{"text": "Point 1", "source": "discussion", "time": "10:15"}]})
        assert resp.status_code == 200

    def test_get_summary(self, server_url):
        resp = papi(server_url, "get", "/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data

    def test_update_notes(self, server_url):
        resp = sapi(server_url, "post", "/notes", json={"content": "Session notes here"})
        assert resp.status_code == 200

    def test_get_notes(self, server_url):
        resp = papi(server_url, "get", "/notes")
        assert resp.status_code == 200
        assert "content" in resp.json()

    def test_transcript_status(self, server_url):
        resp = sapi(server_url, "post", "/transcript-status",
                   json={"line_count": 100, "total_lines": 500, "latest_ts": "10:15:00"})
        assert resp.status_code == 200

    def test_force_summary(self, server_url):
        resp = papi(server_url, "post", "/summary/force")
        assert resp.status_code == 200

    def test_poll_force(self, server_url):
        papi(server_url, "post", "/summary/force")
        resp = sapi(server_url, "get", "/summary/force")
        assert resp.status_code == 200
        assert resp.json()["requested"] is True
        # Second poll should be False
        resp2 = sapi(server_url, "get", "/summary/force")
        assert resp2.json()["requested"] is False
