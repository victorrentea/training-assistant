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
