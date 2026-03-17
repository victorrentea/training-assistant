"""
Integration tests for the main Workshop Tool flow.
Uses FastAPI's TestClient (synchronous) and its WebSocket support.
"""

import json
import pytest
from fastapi.testclient import TestClient

from main import app, state


@pytest.fixture(autouse=True)
def reset_state():
    """Reset in-memory state before each test."""
    state.reset()
    yield
    state.reset()


client = TestClient(app)


def test_create_poll():
    resp = client.post("/api/poll", json={
        "question": "What is your favourite language?",
        "options": ["Python", "Java", "Go"],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["poll"]["question"] == "What is your favourite language?"
    assert len(body["poll"]["options"]) == 3


def test_participant_connects_and_receives_state():
    # Create a poll first so there is something in the state
    client.post("/api/poll", json={
        "question": "Best framework?",
        "options": ["FastAPI", "Django"],
    })

    with client.websocket_connect("/ws/alice") as ws:
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "state"
        assert msg["poll"]["question"] == "Best framework?"
        assert msg["poll_active"] is False
        assert msg["participant_count"] == 1


def receive_until(ws, msg_type: str) -> dict:
    """Read messages from the websocket until one with the given type arrives."""
    for _ in range(10):
        msg = json.loads(ws.receive_text())
        if msg["type"] == msg_type:
            return msg
    raise AssertionError(f"Never received a '{msg_type}' message")


def test_vote_flow():
    # 1. Create poll
    client.post("/api/poll", json={
        "question": "Pick one",
        "options": ["Yes", "No"],
    })

    # 2. Open voting
    client.post("/api/poll/status", json={"open": True})

    # 3. Connect participant, then vote
    with client.websocket_connect("/ws/bob") as ws:
        initial = receive_until(ws, "state")
        assert initial["poll_active"] is True

        option_id = initial["poll"]["options"][0]["id"]

        # 4. Cast a vote
        ws.send_text(json.dumps({"type": "vote", "option_id": option_id}))

        update = receive_until(ws, "vote_update")
        assert update["total_votes"] == 1
        assert update["vote_counts"][option_id] == 1


def test_full_flow():
    """End-to-end: create poll → connect user → open poll → vote → check results."""
    # 1. Create poll
    resp = client.post("/api/poll", json={
        "question": "Tabs or spaces?",
        "options": ["Tabs", "Spaces"],
    })
    assert resp.status_code == 200

    # 2. Open voting
    resp = client.post("/api/poll/status", json={"open": True})
    assert resp.json()["poll_active"] is True

    # 3. Connect participant and vote
    with client.websocket_connect("/ws/charlie") as ws:
        state_msg = receive_until(ws, "state")
        option_id = state_msg["poll"]["options"][1]["id"]  # "Spaces"

        ws.send_text(json.dumps({"type": "vote", "option_id": option_id}))
        update = receive_until(ws, "vote_update")

        assert update["vote_counts"][option_id] == 1

    # 4. Verify via REST
    status = client.get("/api/status").json()
    assert status["total_votes"] == 1
    assert status["vote_counts"][option_id] == 1
