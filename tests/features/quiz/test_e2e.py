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


class TestQuizClearPreview:
    def test_clear_preview(self, server_url):
        resp = sapi(server_url, "delete", "/quiz-preview")
        assert resp.status_code == 200


class TestQuizRefine:
    def test_refine_without_preview(self, server_url):
        sapi(server_url, "delete", "/quiz-preview")
        resp = sapi(server_url, "post", "/quiz-refine", json={"target": "opt0"})
        assert resp.status_code == 400


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
