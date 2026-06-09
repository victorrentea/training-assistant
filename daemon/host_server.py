# daemon/host_server.py
"""Local FastAPI server for the host panel — serves static files and proxies API calls to Railway."""
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, Request, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.host_proxy import create_http_client, proxy_http, proxy_websocket
from daemon.openapi_contract_metadata import enrich_openapi_contract
from daemon.participant.router import host_router as participant_host_router
from daemon.participant.router import router as participant_router

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Set by __main__ after startup so /api/status can expose it
code_timestamp: str | None = None
_persist_log_level = None

# ── Local-only access guard (DNS-rebinding + CSRF defense) ──
# The daemon binds to 127.0.0.1, but loopback binding alone does NOT stop DNS-rebinding:
# a malicious page whose domain resolves to 127.0.0.1 still reaches us — with its own Host
# header. We therefore reject any request whose Host is not a loopback name, and any
# state-changing request carrying a cross-origin Origin. "testserver" is Starlette's
# TestClient default Host and is safe to allow (a browser cannot be coerced into sending it).
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
_ALLOWED_ORIGINS = _ALLOWED_HOSTS | {"interact.victorrentea.ro"}


def _hostname(value: str) -> str:
    """Bare hostname (no port) from a Host header or an Origin URL."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value:
        return (urlparse(value).hostname or "").lower()
    if value.startswith("["):  # bracketed IPv6 literal, optionally with :port
        return value[1:value.index("]")].lower() if "]" in value else ""
    return (value.rsplit(":", 1)[0] if ":" in value else value).lower()


def _local_access_ok(method: str, host: str, origin: str | None) -> bool:
    """True if a request carrying these headers may reach the local daemon."""
    if _hostname(host) not in _ALLOWED_HOSTS:
        return False  # DNS-rebinding / non-loopback Host
    # CSRF: a present, cross-origin Origin on a state-changing request is rejected.
    # WebSocket upgrades (method GET) are validated separately by the caller.
    if origin and method in ("POST", "PUT", "DELETE", "PATCH"):
        return _hostname(origin) in _ALLOWED_ORIGINS
    return True


class LogLevelResponse(BaseModel):
    level: Literal["info", "debug"]


class DaemonStatusResponse(BaseModel):
    code_timestamp: str | None


class SetLogLevelRequest(BaseModel):
    level: Literal["info", "debug"]


def set_log_level_persist_callback(callback) -> None:
    """Register callback(level:str) invoked when log level changes via local API."""
    global _persist_log_level
    _persist_log_level = callback


def _stamp_version_js():
    """Generate static/version.js with 'dev' marker so the daemon can serve it locally."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ts = datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d %H:%M")
    version_js = _STATIC_DIR / "version.js"
    version_js.write_text(f"window.APP_VERSION = '{ts}';\n", encoding="utf-8")


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
        _stamp_version_js()
        yield
        await http_client.aclose()

    app = FastAPI(title="Daemon Host Panel", docs_url=None, redoc_url=None, lifespan=lifespan)

    # OTel: instrument this FastAPI app instance
    try:
        from daemon.telemetry import instrument_fastapi_app
        instrument_fastapi_app(app)
    except ImportError:
        pass

    # Allow the Railway participant landing page to fetch session info from localhost
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://interact.victorrentea.ro"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Participant-ID"],
    )

    # --- Local-only guard: block DNS-rebinding (non-loopback Host) and cross-site CSRF ---
    @app.middleware("http")
    async def _local_access_guard(request: Request, call_next):
        if not _local_access_ok(
            request.method,
            request.headers.get("host", ""),
            request.headers.get("origin"),
        ):
            return JSONResponse({"detail": "Forbidden: local access only"}, status_code=403)
        return await call_next(request)

    # --- No-cache middleware for local dev (prevents stale JS/HTML after daemon restart) ---
    @app.middleware("http")
    async def no_cache_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    # --- Write-back middleware (collects events set by participant router handlers) ---
    @app.middleware("http")
    async def write_back_middleware(request: Request, call_next):
        request.state.write_back_events = []
        if request.url.path.startswith("/api/participant/"):
            daemon_log.debug("railway", f"↓ {request.method} {request.url.path}")
        elif request.url.path.startswith("/api/"):
            daemon_log.debug("host", f"→ {request.method} {request.url.path}")
        response = await call_next(request)
        events = getattr(request.state, "write_back_events", [])
        if events:
            import json as _json
            response.headers["X-Write-Back-Events"] = _json.dumps(events)
        return response

    # --- Host HTML page ---
    @app.get("/")
    async def redirect_root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/host")

    @app.get("/host/{session_id}")
    async def serve_host_page(session_id: str):
        """Serve host.html from local static/ directory."""
        host_html = _STATIC_DIR / "host.html"
        if not host_html.exists():
            return {"error": "host.html not found"}
        return FileResponse(host_html, media_type="text/html")

    @app.get("/host")
    async def serve_host_page_no_session():
        """Serve host-landing.html — lets JS check for active session and redirect to /host/{session_id}."""
        landing_html = _STATIC_DIR / "host-landing.html"
        if not landing_html.exists():
            return {"error": "host-landing.html not found"}
        return FileResponse(landing_html, media_type="text/html")

    # --- Participant identity router (must come BEFORE catch-all to avoid infinite loop) ---
    app.include_router(participant_router)
    app.include_router(participant_host_router)  # /api/{session_id}/host/participants/*

    from daemon.wordcloud.router import host_router as wc_host_router
    from daemon.wordcloud.router import participant_router as wc_participant_router
    app.include_router(wc_participant_router)  # /api/participant/wordcloud/*
    app.include_router(wc_host_router)         # /api/{session_id}/wordcloud/*

    from daemon.emoji.router import host_router as emoji_host_router
    from daemon.emoji.router import participant_router as emoji_participant_router
    from daemon.qa.router import host_router as qa_host_router
    from daemon.qa.router import participant_router as qa_participant_router
    app.include_router(emoji_participant_router)  # /api/participant/emoji/*
    app.include_router(emoji_host_router)          # /api/{session_id}/host/emoji/*
    app.include_router(qa_participant_router)      # /api/participant/qa/*
    app.include_router(qa_host_router)             # /api/{session_id}/qa/*

    from daemon.leaderboard.router import router as leaderboard_router
    from daemon.poll.router import host_router as poll_host_router
    from daemon.poll.router import participant_router as poll_participant_router
    from daemon.quiz.router import host_router as quiz_host_router
    from daemon.quiz.router import participant_router as quiz_participant_router
    app.include_router(quiz_participant_router)   # /api/participant/quiz/*
    app.include_router(quiz_host_router)          # /api/{session_id}/quiz/*
    app.include_router(poll_host_router)          # /api/{session_id}/host/poll/*
    app.include_router(poll_participant_router)   # /api/{session_id}/api/participant/poll/*
    app.include_router(leaderboard_router)        # /api/{session_id}/leaderboard/*

    from daemon.misc.router import host_router as misc_host_router
    from daemon.misc.router import participant_router as misc_participant_router
    app.include_router(misc_participant_router)   # /api/participant/misc/*
    app.include_router(misc_host_router)          # /api/{session_id}/misc/*

    from daemon.quiz_queue.router import router as quiz_queue_router
    app.include_router(quiz_queue_router)         # /api/{session_id}/host/quiz/queue

    from daemon.activity.router import host_router as activity_host_router
    from daemon.codereview.router import host_router as codereview_host_router
    from daemon.codereview.router import participant_router as codereview_participant_router
    app.include_router(codereview_participant_router)  # /api/participant/codereview/*
    app.include_router(codereview_host_router)         # /api/{session_id}/codereview/*
    app.include_router(activity_host_router)           # /api/{session_id}/activity

    from daemon.debate.router import host_router as debate_host_router
    from daemon.debate.router import participant_router as debate_participant_router
    app.include_router(debate_participant_router)  # /api/participant/debate/*
    app.include_router(debate_host_router)         # /api/{session_id}/debate/*

    from daemon.host_state_router import router as host_state_router
    app.include_router(host_state_router)          # /api/{session_id}/host/state

    from daemon.slides.router import participant_router as slides_participant_router
    app.include_router(slides_participant_router)  # /{session_id}/api/slides, /{session_id}/api/slides/check/{slug}

    from daemon.session.router import global_router as session_global_router
    from daemon.session.router import public_router as session_public_router
    app.include_router(session_global_router)      # /api/session/* (host-only: start/end/pause/resume/create/rename/resume-folder/folders)
    app.include_router(session_public_router)      # /api/session/active (public)

    # --- Daemon status endpoint (exposes code_timestamp directly, not proxied) ---
    @app.get("/api/daemon-status", response_model=DaemonStatusResponse)
    async def daemon_status():
        import daemon.host_server as _hs
        return DaemonStatusResponse(code_timestamp=_hs.code_timestamp)

    @app.get("/api/log-level", response_model=LogLevelResponse)
    async def get_log_level():
        return LogLevelResponse(level=daemon_log.get_level())

    @app.post("/api/log-level", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
    async def set_log_level(body: SetLogLevelRequest):
        previous = daemon_log.get_level()
        current = daemon_log.set_level(body.level)
        if _persist_log_level is not None:
            try:
                _persist_log_level(current)
            except Exception as e:
                daemon_log.error("daemon", f"failed persisting log level: {e}")
        daemon_log.info("daemon", f"log level changed via local API: {previous} -> {current}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # --- WebSocket proxy ---
    @app.websocket("/ws/{path:path}")
    async def ws_proxy(websocket: WebSocket, path: str):
        # WebSocket has no CORS preflight, so enforce Host (anti-rebinding) and Origin here,
        # before proxy_websocket() accepts the connection.
        origin = websocket.headers.get("origin")
        host_ok = _hostname(websocket.headers.get("host", "")) in _ALLOWED_HOSTS
        origin_ok = (not origin) or _hostname(origin) in _ALLOWED_ORIGINS
        if not (host_ok and origin_ok):
            await websocket.close(code=1008)  # policy violation
            return
        await proxy_websocket(websocket, path, ws_url)

    # --- API reverse proxy (must come after specific routes) ---
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def api_proxy(request: Request, path: str):
        return await proxy_http(request, f"api/{path}", http_client)

    # --- OpenAPI contract metadata (x-feature/x-doc-notes) ---
    original_openapi = app.openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = original_openapi()
        enrich_openapi_contract(schema)
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi

    # --- Static files (mounted last) ---
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app


def start_host_server(backend_url: str, port: int = 1234) -> threading.Thread:
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
