"""Integration tests for quiz queue router."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.quiz_queue.queue import QuizQueue
from daemon.quiz_queue.router import router

Q1 = {"question": "Q1", "options": ["a", "b"], "correct_indices": [0]}
Q2 = {"question": "Q2", "options": ["c", "d"], "correct_indices": [1]}
Q3 = {"question": "Q3", "options": ["e", "f"], "correct_indices": [0]}


@pytest.fixture
def fresh_queue():
    return QuizQueue()


@pytest.fixture
def client(fresh_queue):
    with patch("daemon.quiz_queue.router.quiz_queue", fresh_queue), \
         patch("daemon.quiz_queue.router.notify_host", AsyncMock()):
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app), fresh_queue


class TestDeleteQueueItem:
    def test_delete_first_item_returns_204(self, client):
        tc, q = client
        q.submit([Q1, Q2])
        resp = tc.delete("/api/test-session/host/quiz/queue/0")
        assert resp.status_code == 204

    def test_delete_removes_correct_item(self, client):
        tc, q = client
        q.submit([Q1, Q2, Q3])
        tc.delete("/api/test-session/host/quiz/queue/1")
        assert q.pending_count() == 2
        assert q.all_items()[0]["question"] == "Q1"
        assert q.all_items()[1]["question"] == "Q3"

    def test_delete_out_of_range_returns_404(self, client):
        tc, q = client
        q.submit([Q1])
        resp = tc.delete("/api/test-session/host/quiz/queue/5")
        assert resp.status_code == 404

    def test_delete_empty_queue_returns_404(self, client):
        tc, q = client
        resp = tc.delete("/api/test-session/host/quiz/queue/0")
        assert resp.status_code == 404
