"""Thread pool handler for proxy_request messages from Railway."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from daemon import log as daemon_log
from daemon.config import DAEMON_HOST_PORT

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="proxy")

# Marker stamped on every request that arrived through Railway. Endpoints that
# are only safe because they are loopback-only (daemon/host_machine/router.py)
# refuse anything carrying it: the local uvicorn socket is reachable both by the
# trainer's browser AND by this proxy, so "came in over 127.0.0.1" alone does
# not prove the caller is on this machine.
RAILWAY_PROXY_MARKER = "x-railway-proxied"


def is_safe_proxy_path(path: str) -> bool:
    """Reject anything that is not an already-clean absolute path.

    This is the fix for a real privilege escalation. Railway matches the raw
    request path, so `/api/participant/../host-machine/claim-trainer` is
    captured by its `/api/participant/{path:path}` catch-all and forwarded
    verbatim. httpx then RESOLVES the dot-segments when building the URL, so the
    request lands on `/api/host-machine/claim-trainer` — an unauthenticated
    endpoint that is only safe while it stays unreachable from the internet.

    "Outside the forwarded prefix" is therefore NOT a security boundary on its
    own. This function is where that boundary is actually enforced, because this
    is the one hop the daemon fully controls.
    """
    if not path.startswith("/"):
        return False
    segments = path.split("?", 1)[0].split("#", 1)[0].split("/")
    if any(seg in ("..", ".") for seg in segments):
        return False
    # Backslashes and encoded separators are normalized inconsistently across
    # the stack; refuse them rather than reason about every combination.
    lowered = path.lower()
    return not any(bad in lowered for bad in ("\\", "%2e", "%2f", "%5c"))


def handle_proxy_request(data: dict, ws_client):
    """Submit proxy_request to thread pool for non-blocking execution.

    Called from drain_queue() on the main thread — must return immediately.
    """
    _executor.submit(_process_proxy_request, data, ws_client)


def _process_proxy_request(data: dict, ws_client):
    """Worker thread: call local FastAPI, send write-back events + proxy_response."""
    req_id = data.get("id")
    method = data.get("method", "GET")
    path = data.get("path", "/")
    body = data.get("body")
    headers = data.get("headers", {})
    # Honor the timeout Railway told us it was waiting for, plus a small buffer
    # so the daemon's local HTTP call doesn't give up just before Railway does.
    try:
        railway_timeout = float(data.get("timeout") or 0.0)
    except (TypeError, ValueError):
        railway_timeout = 0.0
    local_timeout = max(railway_timeout + 5.0, 10.0)

    if not is_safe_proxy_path(path):
        daemon_log.error(
            "proxy", f"↓ REJECTED traversal attempt from Railway: {method} {path}"
        )
        ws_client.send({
            "type": "proxy_response",
            "id": req_id,
            "status": 400,
            "body": json.dumps({"error": "Invalid path"}),
            "content_type": "application/json",
        })
        return

    # Stamp the request so loopback-only endpoints can tell it came from the
    # internet rather than from a browser on this machine.
    headers = {k: v for k, v in headers.items() if k.lower() != RAILWAY_PROXY_MARKER}
    headers[RAILWAY_PROXY_MARKER] = "1"

    url = f"http://127.0.0.1:{DAEMON_HOST_PORT}{path}"

    # Extract trace context from proxy_request (injected by Railway)
    _otel_ctx = None
    try:
        from daemon.telemetry.ws_propagation import extract_trace_context
        _otel_ctx = extract_trace_context(data)
    except ImportError:
        pass

    # If trace context is present, inject it as HTTP headers for the internal call
    if _otel_ctx:
        from opentelemetry import propagate as _propagate
        _propagate.inject(headers, context=_otel_ctx)

    try:
        resp = httpx.request(
            method=method,
            url=url,
            headers=headers,
            content=body.encode("utf-8") if body else None,
            timeout=local_timeout,
        )
    except Exception as e:
        logger.error("Proxy request failed: %s %s — %s", method, path, e)
        ws_client.send({
            "type": "proxy_response",
            "id": req_id,
            "status": 502,
            "body": json.dumps({"error": "Daemon internal error"}),
            "content_type": "application/json",
        })
        return

    # Extract write-back events from response headers (set by daemon participant router)
    write_back_raw = resp.headers.get("x-write-back-events")
    if write_back_raw:
        try:
            events = json.loads(write_back_raw)
            for event in events:
                ws_client.send(event)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse write-back events")

    # Send proxy_response AFTER write-back events
    ws_client.send({
        "type": "proxy_response",
        "id": req_id,
        "status": resp.status_code,
        "body": resp.text,
        "content_type": resp.headers.get("content-type", "application/json"),
    })
