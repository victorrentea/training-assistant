"""Integration tests for daemon↔backend WebSocket protocol."""
import base64
import json
import os
import time

import pytest
import requests
from websockets.sync.client import connect as ws_connect

from conftest import api, sapi


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
            # Drain initial messages (sync_files, slides_updated, etc.)
            time.sleep(0.3)
            while True:
                try:
                    ws.recv(timeout=0.1)
                except Exception:
                    break

            # Host triggers quiz request via REST
            resp = sapi(server_url, "post", "/quiz-request", json={"topic": "testing"})
            assert resp.status_code == 200

            # Daemon should receive quiz_request via WS
            raw = ws.recv(timeout=3)
            msg = json.loads(raw)
            assert msg["type"] == "quiz_request"
            assert msg["request"]["topic"] == "testing"

    def test_daemon_sends_quiz_preview_back(self, server_url):
        """Daemon sends quiz_preview → backend broadcasts it to connected host."""
        # Connect host WS to receive the broadcast
        host_ws_url = server_url.replace("http://", "ws://") + "/ws/__host__"
        with ws_connect(host_ws_url, additional_headers=_auth_headers()) as host_ws:
            # Drain initial state message
            host_ws.recv(timeout=3)

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

                # Host should receive the quiz_preview broadcast
                deadline = time.time() + 3
                found = False
                while time.time() < deadline:
                    try:
                        raw = host_ws.recv(timeout=1)
                        msg = json.loads(raw)
                        if msg.get("type") == "quiz_preview":
                            assert msg["quiz"]["question"] == "What is TDD?"
                            found = True
                            break
                    except Exception:
                        continue
                assert found, "Host did not receive quiz_preview broadcast"

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

    def test_daemon_receives_sync_files_on_connect(self, server_url):
        """Backend sends sync_files with static hashes when daemon connects."""
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            deadline = time.time() + 3
            found = False
            while time.time() < deadline:
                try:
                    raw = ws.recv(timeout=1)
                    msg = json.loads(raw)
                    if msg.get("type") == "sync_files":
                        assert "static_hashes" in msg
                        assert isinstance(msg["static_hashes"], dict)
                        found = True
                        break
                except Exception:
                    continue
            assert found, "Daemon did not receive sync_files on connect"

    def test_slides_endpoint_responds(self, server_url, session_id):
        """GET /{session_id}/api/slides returns 200 (proxied to daemon)."""
        # Railway no longer handles slides_catalog WS messages — daemon is source of truth
        resp = requests.get(f"{server_url}/{session_id}/api/slides")
        assert resp.status_code == 200


def test_host_server_proxies_api_to_backend(server_url):
    """Host server proxies API calls to the Railway backend."""
    from starlette.testclient import TestClient
    from daemon.host_server import create_app

    # Create a host server app pointing to the test backend
    app = create_app(server_url)

    # Use TestClient to test the ASGI app directly (no actual port needed)
    client = TestClient(app)
    # GET /api/status is a public endpoint — should proxy successfully
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "backend_version" in data or "session_active" in data
