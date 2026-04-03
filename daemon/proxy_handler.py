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

    url = f"http://127.0.0.1:{DAEMON_HOST_PORT}{path}"

    try:
        resp = httpx.request(
            method=method,
            url=url,
            headers=headers,
            content=body.encode("utf-8") if body else None,
            timeout=10.0,
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
