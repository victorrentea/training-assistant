# daemon/host_server.py
"""Local FastAPI server for the host panel — serves static files and proxies API calls to Railway."""
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from daemon.host_proxy import create_http_client, proxy_http, proxy_websocket
from daemon.participant.router import router as participant_router

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(backend_url: str) -> FastAPI:
    """Create the host panel FastAPI application.

    Args:
        backend_url: Railway backend URL (e.g., "https://interact.victorrentea.ro")
    """
    # Derive WS URL from HTTP URL
    ws_url = backend_url.replace("https://", "wss://").replace("http://", "ws://")

    # Create shared HTTP client
    http_client = create_http_client(backend_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await http_client.aclose()

    app = FastAPI(title="Daemon Host Panel", docs_url=None, redoc_url=None, lifespan=lifespan)

    # --- Write-back middleware (collects events set by participant router handlers) ---
    @app.middleware("http")
    async def write_back_middleware(request: Request, call_next):
        request.state.write_back_events = []
        response = await call_next(request)
        events = getattr(request.state, "write_back_events", [])
        if events:
            import json as _json
            response.headers["X-Write-Back-Events"] = _json.dumps(events)
        return response

    # --- Host HTML page ---
    @app.get("/host/{session_id}")
    async def serve_host_page(session_id: str):
        """Serve host.html from local static/ directory."""
        host_html = _STATIC_DIR / "host.html"
        if not host_html.exists():
            return {"error": "host.html not found"}
        return FileResponse(host_html, media_type="text/html")

    @app.get("/host")
    async def serve_host_page_no_session():
        """Serve host.html without session ID."""
        host_html = _STATIC_DIR / "host.html"
        if not host_html.exists():
            return {"error": "host.html not found"}
        return FileResponse(host_html, media_type="text/html")

    # --- Participant identity router (must come BEFORE catch-all to avoid infinite loop) ---
    app.include_router(participant_router)

    # --- WebSocket proxy ---
    @app.websocket("/ws/{path:path}")
    async def ws_proxy(websocket: WebSocket, path: str):
        await proxy_websocket(websocket, path, ws_url)

    # --- API reverse proxy (must come after specific routes) ---
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def api_proxy(request: Request, path: str):
        return await proxy_http(request, f"api/{path}", http_client)

    # --- Static files (mounted last) ---
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app


def start_host_server(backend_url: str, port: int = 8081) -> threading.Thread:
    """Start the host panel server in a background daemon thread.

    Returns the thread object (for testing/shutdown).
    """
    app = create_app(backend_url)

    def _run():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)

    thread = threading.Thread(target=_run, daemon=True, name="host-server")
    thread.start()
    logger.info("Host panel server started on http://127.0.0.1:%d", port)
    return thread
