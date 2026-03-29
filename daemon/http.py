"""
HTTP helper utilities for communicating with the workshop server.
"""

import base64
import json
import os
import socket
import ssl
import urllib.error
import urllib.request

from daemon import log

# ---------------------------------------------------------------------------
# SSL / timeout
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_HTTP_ERROR_HINTS = {
    401: "wrong credentials (check HOST_USERNAME / HOST_PASSWORD)",
    403: "access denied (check Caddy basic_auth config)",
    404: "endpoint missing (server outdated?)",
    500: "server internal error (check uvicorn logs)",
    502: "bad gateway (reverse proxy issue — Caddy/nginx)",
    503: "server unavailable (workshop service may be down)",
}

_HTTP_TIMEOUT_SECONDS = float(os.environ.get("WORKSHOP_HTTP_TIMEOUT_SECONDS", "8"))


def _http_error_message(code: int, url: str) -> str:
    hint = _HTTP_ERROR_HINTS.get(code, "unexpected server response")
    return f"HTTP {code} — {hint} [{url}]"


# ---------------------------------------------------------------------------
# Core request helpers
# ---------------------------------------------------------------------------

def _urlopen_json(req: urllib.request.Request, url: str) -> dict:
    """Execute a prepared request, parse JSON, and wrap errors with helpful messages."""
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS, context=_ssl_context()) as resp:
            try:
                return json.loads(resp.read())
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from server [{url}]") from e
    except urllib.error.HTTPError as e:
        raise RuntimeError(_http_error_message(e.code, url)) from e
    except (TimeoutError, socket.timeout) as e:
        raise RuntimeError(f"Server request timed out after {_HTTP_TIMEOUT_SECONDS:.1f}s [{url}]") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach server: {e.reason} [{url}]") from e
    except OSError as e:
        raise RuntimeError(f"Cannot reach server: {e} [{url}]") from e


def _request_json(url: str, payload: dict, method: str = "POST", username: str = "", password: str = "") -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if username:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return _urlopen_json(req, url)


def _post_json(url: str, payload: dict, username: str = "", password: str = "") -> dict:
    return _request_json(url, payload, method="POST", username=username, password=password)


def session_api_url(base_url: str, session_id: str | None, path: str) -> str:
    """Build a session-scoped API URL. Falls back to non-scoped if session_id is None."""
    if session_id:
        return f"{base_url}/api/{session_id}{path}"
    return f"{base_url}/api{path}"


def _get_json(url: str, username: str = "", password: str = "") -> dict:
    headers = {}
    if username:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, headers=headers)
    return _urlopen_json(req, url)


def get_active_session_id(server_url: str) -> str | None:
    """Fetch the active session_id from the server. Returns None if server is unreachable or no active session."""
    try:
        data = _get_json(f"{server_url}/api/session/active")
        return data.get("session_id") if data.get("active") else None
    except Exception:
        return None
