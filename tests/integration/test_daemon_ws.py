"""Integration tests for daemon↔backend WebSocket protocol."""
import base64
import json
import os
import time

import pytest
import requests
from websockets.sync.client import connect as ws_connect

from conftest import api


def _daemon_ws_url(server_url: str) -> str:
    return server_url.replace("http://", "ws://") + "/ws/daemon"


def _auth_headers() -> dict:
    user = os.environ.get("HOST_USERNAME", "host")
    pw = os.environ.get("HOST_PASSWORD", "testpass")
    creds = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


class TestDaemonWsProtocol:
    """Test that backend pushes work requests to daemon via WS and accepts results."""

    def test_daemon_connects_and_receives_heartbeat(self, server_url):
        """Daemon WS connection is accepted with valid auth."""
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            # Connection accepted — send a ping (heartbeat only, no response expected)
            ws.send(json.dumps({"type": "daemon_ping"}))
            time.sleep(0.2)
            # No exception means connection stayed open

    def test_daemon_rejects_unauthenticated_connection(self, server_url):
        """Daemon WS endpoint rejects connections without valid auth."""
        with pytest.raises(Exception):
            # No auth headers — should be rejected with close code 1008
            ws_connect(_daemon_ws_url(server_url)).close()

    def test_quiz_request_pushed_to_daemon(self, server_url):
        """Host requests quiz → backend pushes quiz_request to daemon WS."""
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            # Host triggers quiz request via REST
            resp = api(server_url, "post", "/api/quiz-request", json={"topic": "testing"})
            assert resp.status_code == 200

            # Daemon should receive quiz_request via WS
            raw = ws.recv(timeout=3)
            msg = json.loads(raw)
            assert msg["type"] == "quiz_request"
            assert msg["request"]["topic"] == "testing"

    def test_daemon_sends_quiz_preview_back(self, server_url):
        """Daemon sends quiz_preview → backend stores it; host can retrieve it via quiz-refine poll."""
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            # Daemon sends a quiz preview
            ws.send(json.dumps({
                "type": "quiz_preview",
                "quiz": {
                    "question": "What is TDD?",
                    "options": [
                        {"id": "a", "text": "Test-Driven Development"},
                        {"id": "b", "text": "Type-Driven Design"},
                    ],
                    "multi": False,
                    "correct_indices": [0],
                }
            }))

            time.sleep(0.3)  # Let backend process

            # Verify the preview was stored — GET /api/quiz-refine is auth-protected and returns current preview
            resp = api(server_url, "get", "/api/quiz-refine")
            assert resp.status_code == 200
            data = resp.json()
            assert data["preview"] is not None
            assert data["preview"]["question"] == "What is TDD?"

    def test_session_sync_via_ws(self, server_url, session_id):
        """Daemon sends session_sync → backend updates summary points (readable via public endpoint)."""
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            ws.send(json.dumps({
                "type": "session_sync",
                "main": {"name": "Test Session", "status": "active"},
                "talk": None,
                "key_points": [{"text": "Point from WS", "time": "10:00", "source": "notes"}],
            }))

            time.sleep(0.3)

            # GET /api/summary is a public endpoint mounted under /{session_id}
            resp = requests.get(f"{server_url}/{session_id}/api/summary")
            assert resp.status_code == 200
            data = resp.json()
            points = data.get("points", [])
            assert any(p.get("text") == "Point from WS" for p in points)

    def test_slides_catalog_via_ws(self, server_url, session_id):
        """Daemon sends slides_catalog → backend accepts it; slides endpoint responds."""
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            ws.send(json.dumps({
                "type": "slides_catalog",
                "entries": [
                    {
                        "slug": "ws-test-deck",
                        "name": "WS Test Deck",
                        "target_pdf": "ws-test-deck.pdf",
                        "drive_export_url": None,
                    }
                ]
            }))

            time.sleep(0.3)

            # GET /api/slides is a public endpoint mounted under /{session_id}
            resp = requests.get(f"{server_url}/{session_id}/api/slides")
            assert resp.status_code == 200
