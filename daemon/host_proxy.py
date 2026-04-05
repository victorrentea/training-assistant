# daemon/host_proxy.py
"""HTTP and WebSocket reverse proxy for host panel → Railway backend."""
import asyncio
import logging

import httpx
from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

logger = logging.getLogger(__name__)

# Headers to strip from proxied responses.
# Includes hop-by-hop headers + content-encoding (httpx auto-decompresses,
# so forwarding this header with decompressed body would corrupt the response).
_STRIP_HEADERS = frozenset({
    "transfer-encoding", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "upgrade", "content-encoding",
})


def create_http_client(backend_url: str) -> httpx.AsyncClient:
    """Create a reusable async HTTP client for proxying to the backend."""
    return httpx.AsyncClient(base_url=backend_url, timeout=30.0)


async def proxy_http(request: Request, path: str, http_client: httpx.AsyncClient) -> Response:
    """Forward an HTTP request to the backend and return the response."""
    url = f"/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    # Forward all headers except host
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)  # httpx recalculates

    body = await request.body()

    try:
        resp = await http_client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )
    except httpx.ConnectError:
        return Response(content='{"error": "Backend unreachable"}', status_code=502,
                        media_type="application/json")
    except httpx.TimeoutException:
        return Response(content='{"error": "Backend timeout"}', status_code=504,
                        media_type="application/json")

    # Filter hop-by-hop headers from response
    resp_headers = {k: v for k, v in resp.headers.items()
                    if k.lower() not in _STRIP_HEADERS}

    return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)



async def proxy_websocket(client_ws: WebSocket, path: str, backend_ws_url: str):
    """Proxy a WebSocket connection bidirectionally between client and backend."""
    import ssl
    import websockets
    from websockets.exceptions import ConnectionClosed

    await client_ws.accept()

    is_host = path.endswith("__host__")
    if is_host:
        from daemon.ws_publish import set_host_ws
        set_host_ws(client_ws)

    url = f"{backend_ws_url}/ws/{path}"

    # Forward auth header
    extra_headers = {}
    auth = client_ws.headers.get("authorization")
    if auth:
        extra_headers["Authorization"] = auth

    # Skip SSL verification — daemon is a local trusted process, cert checks unnecessary
    ws_kwargs = {"additional_headers": extra_headers}
    if url.startswith("wss://"):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        ws_kwargs["ssl"] = ssl_ctx

    try:
        async with websockets.connect(url, **ws_kwargs) as upstream:

            async def client_to_upstream():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await upstream.send(data)
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        await client_ws.send_text(message)
                except ConnectionClosed:
                    pass

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_upstream()),
                 asyncio.create_task(upstream_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.warning("WS proxy error for /ws/%s: %s", path, e)
    finally:
        if is_host:
            from daemon.ws_publish import clear_host_ws
            clear_host_ws()
        try:
            await client_ws.close()
        except Exception:
            pass
