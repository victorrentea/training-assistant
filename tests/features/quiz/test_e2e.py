"""E2E tests for features/quiz router."""
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


# ── Summary read endpoints (public, session-scoped) ───────────────────

class TestSummaryRead:
    def test_get_summary(self, server_url):
        resp = papi(server_url, "get", "/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data

    def test_get_notes(self, server_url):
        resp = papi(server_url, "get", "/notes")
        assert resp.status_code == 200
        assert "content" in resp.json()
