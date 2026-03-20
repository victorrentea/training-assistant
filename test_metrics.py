"""Tests for Prometheus metrics endpoint."""

import base64
import os
import pytest
from fastapi.testclient import TestClient

from main import app, state
import auth  # noqa: ensure secrets.env is loaded

_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


def test_metrics_endpoint_requires_auth():
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 401


def test_metrics_endpoint_returns_prometheus_format():
    client = TestClient(app)
    resp = client.get("/metrics", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.text
    # Auto-instrumented metrics should be present
    assert "http_request" in body
    # Custom metrics should be present
    assert "ws_connections_active" in body
    assert "poll_votes_total" in body
    assert "qa_questions_total" in body


import json
from prometheus_client import REGISTRY


def _get_metric_value(name, labels=None):
    """Get current value of a Prometheus metric by sample name.

    For Counters, prometheus_client strips '_total' from metric.name but keeps it in
    sample.name.  We match on sample.name so callers can use the full metric name
    (e.g. 'poll_votes_total') or the base name (e.g. 'ws_connections_active').
    Skips '_created' samples automatically.
    """
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name.endswith("_created"):
                continue
            if sample.name == name or metric.name == name:
                if labels is None or all(sample.labels.get(k) == v for k, v in labels.items()):
                    return sample.value
    return None


def test_ws_connection_increments_gauge():
    """WebSocket connect should increment ws_connections_active."""
    client = TestClient(app)
    before = _get_metric_value("ws_connections_active", {"role": "participant"}) or 0
    with client.websocket_connect("/ws/test-metrics-participant") as ws:
        ws.send_text(json.dumps({"type": "set_name", "name": "MetricsTest"}))
        # Drain initial state message
        for _ in range(5):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "state":
                break
        during = _get_metric_value("ws_connections_active", {"role": "participant"})
        assert during is not None
        assert during > before
    # After disconnect, gauge should go back
    after = _get_metric_value("ws_connections_active", {"role": "participant"})
    assert after == before


def test_vote_increments_counter():
    """Voting should increment poll_votes_total."""
    # Reset state to avoid stale participants causing broadcast hangs
    state.reset()
    client = TestClient(app)
    before = _get_metric_value("poll_votes_total", {}) or 0

    # Create and open a poll via host API
    resp = client.post("/api/poll", json={
        "question": "Metrics test?",
        "options": ["Yes", "No"],
    }, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    poll_data = resp.json()["poll"]
    option_id = poll_data["options"][0]["id"]  # first option id
    client.put("/api/poll/status", json={"open": True}, headers=_HOST_AUTH_HEADERS)

    with client.websocket_connect("/ws/test-metrics-voter") as ws:
        ws.send_text(json.dumps({"type": "set_name", "name": "Voter"}))
        for _ in range(20):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "state":
                break
        ws.send_text(json.dumps({"type": "vote", "option_id": option_id}))
        for _ in range(20):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "vote_update":
                break

    after = _get_metric_value("poll_votes_total", {})
    assert after is not None
    assert after > before

    # Cleanup
    state.reset()


def test_ws_messages_tracked_by_type():
    """Every WS message should increment ws_messages_total with type label."""
    client = TestClient(app)
    before = _get_metric_value("ws_messages_total", {"type": "set_name"}) or 0
    with client.websocket_connect("/ws/test-metrics-msg") as ws:
        ws.send_text(json.dumps({"type": "set_name", "name": "MsgTest"}))
        for _ in range(5):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "state":
                break
    after = _get_metric_value("ws_messages_total", {"type": "set_name"})
    assert after is not None
    assert after > before
