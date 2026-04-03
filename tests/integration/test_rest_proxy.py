"""Integration tests for REST proxy: participant → Railway → daemon → response."""
import json
import os
import time
import base64

import pytest
import requests
from websockets.sync.client import connect as ws_connect


def _daemon_ws_url(server_url: str) -> str:
    return server_url.replace("http://", "ws://") + "/ws/daemon"


def _auth_headers() -> dict:
    user = os.environ.get("HOST_USERNAME", "host")
    pw = os.environ.get("HOST_PASSWORD", "testpass")
    creds = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


class TestRestProxy:
    """Test the REST proxy chain: participant REST → Railway → daemon WS → response."""

    @pytest.mark.nightly
    def test_participant_name_via_proxy(self, server_url, session_id):
        """POST /api/participant/name is proxied to daemon and returns success."""
        # Connect daemon WS so proxy has a target
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            # Drain initial messages
            time.sleep(0.3)
            while True:
                try:
                    ws.recv(timeout=0.1)
                except Exception:
                    break

            # Make participant REST call
            resp = requests.post(
                f"{server_url}/{session_id}/api/participant/name",
                json={"name": "TestProxy"},
                headers={"X-Participant-ID": "proxy-test-uuid"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("ok") is True
            assert data.get("name") == "TestProxy"

    def test_proxy_returns_503_without_daemon(self, server_url, session_id):
        """Without daemon connected, proxy returns 503."""
        resp = requests.post(
            f"{server_url}/{session_id}/api/participant/name",
            json={"name": "NoBody"},
            headers={"X-Participant-ID": "no-daemon-uuid"},
        )
        assert resp.status_code == 503
