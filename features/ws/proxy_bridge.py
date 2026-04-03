"""Generic REST proxy bridge: forwards participant HTTP calls to daemon via WS."""
import asyncio
import logging
import uuid as _uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from core.state import state

logger = logging.getLogger(__name__)

# Correlation ID → asyncio.Future for pending proxy requests
_pending_requests: dict[str, asyncio.Future] = {}

# Default timeout for proxy requests (seconds)
PROXY_TIMEOUT = 5.0


async def proxy_to_daemon(method: str, path: str, body: bytes | None,
                          headers: dict, participant_id: str | None) -> Response:
    """Forward a participant REST call to daemon via WS proxy_request/proxy_response."""
    ws = state.daemon_ws
    if ws is None:
        return JSONResponse({"error": "Trainer not connected"}, status_code=503)

    req_id = _uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending_requests[req_id] = future

    # Build proxy_request message
    msg = {
        "type": "proxy_request",
        "id": req_id,
        "method": method,
        "path": path,
        "body": body.decode("utf-8", errors="replace") if body else None,
        "headers": {k: v for k, v in headers.items()
                    if k.lower() not in ("host", "content-length")},
        "participant_id": participant_id,
    }

    try:
        await ws.send_json(msg)
    except Exception:
        _pending_requests.pop(req_id, None)
        return JSONResponse({"error": "Trainer not connected"}, status_code=503)

    try:
        result = await asyncio.wait_for(future, timeout=PROXY_TIMEOUT)
    except asyncio.TimeoutError:
        _pending_requests.pop(req_id, None)
        logger.warning("Proxy request timed out: %s %s", method, path)
        return JSONResponse({"error": "Trainer not responding"}, status_code=503)

    _pending_requests.pop(req_id, None)

    return Response(
        content=result.get("body", ""),
        status_code=result.get("status", 500),
        media_type=result.get("content_type", "application/json"),
    )


async def handle_proxy_response(data: dict):
    """Handle proxy_response from daemon — resolve the pending Future."""
    req_id = data.get("id")
    if not req_id:
        logger.warning("proxy_response missing 'id' field")
        return
    future = _pending_requests.get(req_id)
    if future is None:
        logger.warning("proxy_response for unknown/expired id: %s", req_id)
        return
    if not future.done():
        future.set_result(data)


# ── Catch-all participant proxy route ──

participant_proxy_router = APIRouter()


@participant_proxy_router.api_route(
    "/api/participant/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=False,
)
async def participant_proxy(request: Request, path: str):
    """Forward all /api/participant/* calls to daemon via WS proxy."""
    participant_id = request.headers.get("x-participant-id")
    return await proxy_to_daemon(
        method=request.method,
        path=f"/api/participant/{path}",
        body=await request.body(),
        headers=dict(request.headers),
        participant_id=participant_id,
    )
