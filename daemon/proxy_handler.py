"""Thread pool handler for proxy_request messages from Railway."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from daemon.config import DAEMON_HOST_PORT

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="proxy")


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
