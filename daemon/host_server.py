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

# Set by __main__ after startup so /api/status can expose it
code_timestamp: str | None = None


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
        """Serve host-landing.html — lets JS check for active session and redirect to /host/{session_id}."""
        landing_html = _STATIC_DIR / "host-landing.html"
        if not landing_html.exists():
            return {"error": "host-landing.html not found"}
        return FileResponse(landing_html, media_type="text/html")

    # --- Participant identity router (must come BEFORE catch-all to avoid infinite loop) ---
    app.include_router(participant_router)

    from daemon.wordcloud.router import participant_router as wc_participant_router
    from daemon.wordcloud.router import host_router as wc_host_router
    app.include_router(wc_participant_router)  # /api/participant/wordcloud/*
    app.include_router(wc_host_router)         # /api/{session_id}/wordcloud/*

    from daemon.emoji.router import participant_router as emoji_participant_router
    from daemon.qa.router import participant_router as qa_participant_router
    from daemon.qa.router import host_router as qa_host_router
    app.include_router(emoji_participant_router)  # /api/participant/emoji/*
    app.include_router(qa_participant_router)      # /api/participant/qa/*
    app.include_router(qa_host_router)             # /api/{session_id}/qa/*

    from daemon.poll.router import participant_router as poll_participant_router
    from daemon.poll.router import host_router as poll_host_router
    from daemon.poll.router import quiz_md_router
    from daemon.leaderboard.router import router as leaderboard_router
    app.include_router(poll_participant_router)   # /api/participant/poll/*
    app.include_router(poll_host_router)          # /api/{session_id}/poll/*
    app.include_router(quiz_md_router)            # /api/{session_id}/quiz-md
    app.include_router(leaderboard_router)        # /api/{session_id}/leaderboard/*

    from daemon.misc.router import participant_router as misc_participant_router
    from daemon.misc.router import host_router as misc_host_router
    from daemon.misc.router import global_router as misc_global_router
    app.include_router(misc_participant_router)   # /api/participant/misc/*
    app.include_router(misc_host_router)          # /api/{session_id}/misc/*
    app.include_router(misc_global_router)        # /api/transcription-language (global, no session_id)

    from daemon.quiz.router import host_router as quiz_host_router
    app.include_router(quiz_host_router)          # /api/{session_id}/quiz-request, /quiz-preview, /quiz-refine

    from daemon.codereview.router import participant_router as codereview_participant_router
    from daemon.codereview.router import host_router as codereview_host_router
    from daemon.activity.router import host_router as activity_host_router
    app.include_router(codereview_participant_router)  # /api/participant/codereview/*
    app.include_router(codereview_host_router)         # /api/{session_id}/codereview/*
    app.include_router(activity_host_router)           # /api/{session_id}/activity

    from daemon.debate.router import participant_router as debate_participant_router
    from daemon.debate.router import host_router as debate_host_router
    app.include_router(debate_participant_router)  # /api/participant/debate/*
    app.include_router(debate_host_router)         # /api/{session_id}/debate/*

    from daemon.host_state_router import router as host_state_router
    app.include_router(host_state_router)          # /api/{session_id}/host/state

    from daemon.slides.router import participant_router as slides_participant_router
    app.include_router(slides_participant_router)  # /{session_id}/api/slides, /{session_id}/api/slides/check/{slug}

    from daemon.session.router import global_router as session_global_router
    from daemon.session.router import public_router as session_public_router
    from daemon.session.router import session_router as session_scoped_router
    app.include_router(session_global_router)      # /api/session/* (host-only: start/end/pause/resume/create/rename/resume-folder/folders/start_talk/end_talk)
    app.include_router(session_public_router)      # /api/session/active (public)
    app.include_router(session_scoped_router)      # /api/{session_id}/session/interval-lines.txt

    # --- Daemon status endpoint (exposes code_timestamp directly, not proxied) ---
    from fastapi.responses import JSONResponse
    @app.get("/api/daemon-status")
    async def daemon_status():
        import daemon.host_server as _hs
        return JSONResponse({"code_timestamp": _hs.code_timestamp})

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
