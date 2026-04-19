"""Workshop Live Interaction Tool — FastAPI + WebSocket backend."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

import railway.shared.metrics as metrics  # noqa: F401 - import for Prometheus metric registration side effects
from railway.features.inbox.router import router as inbox_router
from railway.features.internal.router import router as internal_router
from railway.features.pages.router import host_router, landing_router, participant_router
from railway.features.session.notes_router import public_router as session_public_router
from railway.features.slides import router as slides
from railway.features.slides.upload import router as slides_upload_router
from railway.features.upload import router as upload
from railway.features.upload.router import public_router as upload_public_router
from railway.features.ws import router as ws
from railway.features.ws.proxy_bridge import participant_proxy_router
from railway.features.ws.router import session_router as ws_session_router
from railway.shared.auth import require_host_auth
from railway.shared.session_guard import InvalidSessionRedirect, require_valid_session
from railway.shared.state import state  # re-exported for tests: from railway.app import app, state

logging.basicConfig(level=logging.INFO)

# OTel tracing — provider setup (before app creation, instrumentor applied after)
_otel_active = False
if os.environ.get("OTEL_TRACES_FILE"):
    try:
        from daemon.telemetry import instrument_urllib, setup_tracing
        setup_tracing()
        instrument_urllib()
        _otel_active = True
    except Exception as _otel_err:
        logging.getLogger(__name__).warning("OTel setup failed: %s", _otel_err)

PROJECT_ROOT = Path(__file__).parent.parent
_RAILWAY_STARTED_AT_ISO: str | None = None


def _stamp_version_js():
    """Generate static/version.js with the current Bucharest timestamp at startup."""
    ts = datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d %H:%M")
    version_js = PROJECT_ROOT / "static" / "version.js"
    version_js.write_text(f"window.APP_VERSION = '{ts}';\n", encoding="utf-8")
    logging.getLogger(__name__).info("version.js stamped: %s", ts)


def _stamp_deploy_info():
    """Generate static/deploy-info.json from Railway env vars at startup (no git needed)."""
    import json

    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")
    if not sha:
        return  # local dev — skip, file may be stale or absent
    msg = os.environ.get("RAILWAY_GIT_COMMIT_MESSAGE", "")
    ts = datetime.now(ZoneInfo("Europe/Bucharest")).isoformat()
    deploy_info = {
        "sha": sha[:8],
        "timestamp": datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d %H:%M"),
        "changelog": [msg] if msg else [],
        "commits": [{"sha": sha[:8], "msg": msg, "ts": ts}] if msg else [],
        "branches": [],
    }
    path = PROJECT_ROOT / "static" / "deploy-info.json"
    path.write_text(json.dumps(deploy_info, indent=2), encoding="utf-8")
    logging.getLogger(__name__).info("deploy-info.json stamped: %s", sha[:8])


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _RAILWAY_STARTED_AT_ISO
    _RAILWAY_STARTED_AT_ISO = datetime.now(ZoneInfo("Europe/Bucharest")).isoformat()
    _stamp_version_js()
    _stamp_deploy_info()
    yield


app = FastAPI(title="Workshop Tool", lifespan=lifespan)

# Instrument this specific app instance for OTel
if _otel_active:
    try:
        from daemon.telemetry import instrument_fastapi_app
        instrument_fastapi_app(app)
    except Exception:
        pass


@app.exception_handler(InvalidSessionRedirect)
async def _redirect_invalid_session(request: Request, exc: InvalidSessionRedirect):
    from fastapi.responses import RedirectResponse

    from railway.shared.state import state as _state
    if _state.session_id:
        return RedirectResponse(f"/{_state.session_id}")
    return RedirectResponse("/?error=invalid")


@app.middleware("http")
async def add_avatar_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/avatars/") and path.endswith(".png"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", dependencies=[Depends(require_host_auth)]
)

# ── Root-level routes (registered FIRST to prevent /{session_id} catch-all conflicts) ──

# WebSocket: daemon + host (no session prefix)
app.include_router(ws.router)
# WebSocket: session-scoped participant connections
app.include_router(ws_session_router)

# AgentMail webhook receiver + claude-inbox WebSocket
app.include_router(inbox_router)

# Pages: landing at /, host at /host (auth-protected)
app.include_router(landing_router)
app.include_router(host_router)

# Daemon-facing slides endpoints (global — daemon doesn't know session_id)
app.include_router(slides_upload_router, dependencies=[Depends(require_host_auth)])
app.include_router(slides.daemon_router, dependencies=[Depends(require_host_auth)])

# Internal daemon → backend file management endpoints
app.include_router(internal_router)


# ── Session-scoped host dependency ──

async def _require_active_session_host(session_id: str):
    """Validates that the session_id in the path matches the active session."""
    if not state.session_id or session_id.lower() != state.session_id.lower():
        raise HTTPException(status_code=404, detail="Session not found or not active")


# ── Session-scoped host router (/api/{session_id}/...) ──

session_host = APIRouter(
    prefix="/api/{session_id}",
    dependencies=[Depends(require_host_auth), Depends(_require_active_session_host)],
)
session_host.include_router(slides.router)
session_host.include_router(upload.router)


app.include_router(session_host)

# ── Session-scoped participant routes (registered LAST — /{session_id} is a catch-all) ──

session_participant = APIRouter(
    prefix="/{session_id}",
    dependencies=[Depends(require_valid_session)],
)
session_participant.include_router(participant_router)       # /, /notes, /poll
session_participant.include_router(slides.public_router)     # /api/slides, /api/slides/file/{slug}, /api/slides/current
session_participant.include_router(session_public_router)    # /api/summary, /api/notes
session_participant.include_router(upload_public_router)     # /api/upload (participant file upload)
session_participant.include_router(participant_proxy_router)  # /api/participant/* → daemon proxy
app.include_router(session_participant)

if os.environ.get("OTEL_TRACES_FILE"):
    from railway.features.telemetry.router import router as telemetry_router
    app.include_router(telemetry_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Minimal session bootstrap endpoints (used by e2e test setup when daemon is not running) ──

@app.post("/api/session/start", dependencies=[Depends(require_host_auth)])
async def session_start():
    """Generate a session_id. Used by conftest when daemon is not running."""
    return {"session_id": state.generate_session_id()}


@app.get("/api/session/active")
async def session_active():
    """Return current session_id. Fallback used by conftest."""
    return {"session_id": state.session_id}


@app.get("/api/is-active-session")
async def is_active_session():
    """Public endpoint: returns whether daemon is connected and any session is active.

    A session is only considered active when BOTH session_id exists AND daemon is connected.
    When daemon disconnects, session_id may linger in state but the session is not usable.
    """
    daemon_connected = state.daemon_ws is not None
    return {
        "active": daemon_connected and state.session_id is not None,
        "daemon_connected": daemon_connected,
    }


# ── Public status endpoint (version probe + session state) ──

@app.get("/api/status")
async def get_status():
    """Public endpoint: backend version, active session info, and current slides."""
    from railway.shared.version import get_backend_version
    return {
        "backend_version": get_backend_version(),
        "git_sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA", ""),
        "daemon_code_timestamp": state.daemon_code_timestamp,
        "railway_started_at": _RAILWAY_STARTED_AT_ISO,
        "session_active": state.session_id is not None,
        "session_id": state.session_id,
        "slides_current": state.slides_current,
    }


@app.get("/{session_id}/api/status")
async def get_session_status(session_id: str, _=Depends(require_valid_session)):
    """Session-scoped public status endpoint — returns 200 for valid session, 404 for invalid."""
    from railway.shared.version import get_backend_version
    return {
        "backend_version": get_backend_version(),
        "git_sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA", ""),
        "daemon_code_timestamp": state.daemon_code_timestamp,
        "railway_started_at": _RAILWAY_STARTED_AT_ISO,
        "session_active": True,
        "session_id": state.session_id,
        "slides_current": state.slides_current,
    }
