import os
from datetime import datetime
from html import escape as _html_escape
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from railway.shared.auth import get_host_cookie_token, require_host_auth
from railway.shared.rate_limit import rate_limit_probe
from railway.shared.session_registry import session_registry
from railway.shared.state import state

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static"
_ENDED_TEMPLATE = _STATIC_DIR / "session-ended.html"

landing_router = APIRouter()
host_router = APIRouter()
participant_router = APIRouter()

_OTEL_ENABLED = bool(os.environ.get("OTEL_TRACES_FILE"))

# ── Content-Security-Policy (defense-in-depth for the participant-name XSS) ──
# Crafted from an audit of what the railway-served pages actually load:
#   landing/host-landing/notes: self + inline <script>/<style>
#   host.html:  Leaflet (unpkg CSS+JS), QRCode/d3/d3-cloud/OTel (jsdelivr),
#               highlight.js (cdnjs), OSM map tiles (arbitrary https img)
#   participant.html: fonts (googleapis/gstatic), pdf.js + marked + mammoth +
#               canvas-confetti (jsdelivr; pdf.js spins a worker from a blob it
#               fetches from jsdelivr), self-hosted tailwind.css
#   talk.html:  Tailwind Play CDN (cdn.tailwindcss.com — needs 'unsafe-eval'),
#               marked (jsdelivr), fonts (googleapis/gstatic)
# Every page relies on inline <script> blocks and inline event handlers, so
# 'unsafe-inline'/'unsafe-eval' are required to avoid breaking them; the value
# is host-allowlisting + connect-src restriction (blocks injected external
# scripts and exfiltration to arbitrary origins).
_CSP = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'self'",
    "form-action 'self'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
    "https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com "
    "https://cdn.tailwindcss.com",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net "
    "https://unpkg.com https://cdnjs.cloudflare.com https://cdn.tailwindcss.com",
    "worker-src 'self' blob: https://cdn.jsdelivr.net",
    "connect-src 'self' https://cdn.jsdelivr.net https://nominatim.openstreetmap.org",
])


def _with_csp(response: Response) -> Response:
    """Attach the Content-Security-Policy header to a page response."""
    response.headers["Content-Security-Policy"] = _CSP
    return response


def _serve_html_with_otel(path: str, service_name: str = "Browser") -> HTMLResponse | FileResponse:
    """Serve an HTML file, injecting OTel meta tags when telemetry is active."""
    if not _OTEL_ENABLED:
        return _with_csp(FileResponse(path))
    html = open(path, encoding="utf-8").read()
    meta = (
        f'  <meta name="otel-endpoint" content="/api/telemetry/spans">\n'
        f'  <meta name="otel-service-name" content="{service_name}">\n'
    )
    html = html.replace("</head>", f"{meta}</head>", 1)
    return _with_csp(HTMLResponse(html))


@landing_router.get("/", response_class=HTMLResponse)
async def landing_page():
    return _with_csp(FileResponse("static/landing.html"))


@landing_router.get("/new", response_class=HTMLResponse)
async def new_page():
    return _with_csp(FileResponse("static/new/code.html"))


@host_router.get("/host/", response_class=HTMLResponse)
async def host_landing_redirect():
    return RedirectResponse(url="/host", status_code=301)


@host_router.get("/host", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_landing():
    response = FileResponse("static/host-landing.html")
    response.set_cookie("is_host", get_host_cookie_token(), path="/", samesite="strict", httponly=True)
    return _with_csp(response)


@host_router.get("/host/{session_id}", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_page(session_id: str):
    response = _serve_html_with_otel("static/host.html", service_name="Host")
    response.set_cookie("is_host", get_host_cookie_token(), path="/", samesite="strict", httponly=True)
    return response


# Valid participant SPA tab slugs that may appear as the path segment after the
# session id (mirrors the VIEWS array in static/participant.html, plus the
# past-slides panel). Unknown slugs 404 so the catch-all cannot swallow garbage.
_PARTICIPANT_TAB_SLUGS = frozenset(
    {
        "slides",
        "activity",
        "summary",
        "notes",
        "agenda",
        "feedback",
        "upload-paste",
        "files",
        "past-slides",
        "about",
    }
)


def _is_active_session(session_id: str) -> bool:
    """True only for the currently-live session (case-insensitive, matching the
    guards). A registry-valid recent-PAST id is NOT active."""
    return bool(state.session_id) and session_id.lower() == state.session_id.lower()


def _serve_ended_session_page(session_id: str) -> HTMLResponse:
    """Read-only "this session has ended" landing for a recent PAST session.

    SECURITY (anti-hijack): a recent-past id is registry-valid, so
    ``require_valid_session`` lets the page route through — but it is NOT the live
    session. It must never receive the participant SPA: that shell opens a live
    participant WebSocket and proxies to the daemon, which would leak the CURRENT
    cohort's session into the old link. We serve a dedicated static page instead,
    distinct from the generic ``/?error=invalid`` shown for UNKNOWN ids.

    We surface only the session id + date, which Railway *does* hold (the
    in-memory registry entry). Richer archived content (saved summary / attendees
    / notes) is NOT served: the daemon owns the session folder and is connected
    only for the CURRENTLY active session, so a past session's material is
    unreachable from the gateway. Serving it would need daemon/archive plumbing
    (out of scope).
    """
    entry = session_registry.get(session_id) or {}
    when_iso = entry.get("ended_at") or entry.get("created_at") or ""
    suffix = ""
    if when_iso:
        try:
            suffix = " &middot; " + _html_escape(datetime.fromisoformat(when_iso).strftime("%Y-%m-%d"))
        except ValueError:
            suffix = ""
    html = _ENDED_TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("{{SESSION_DATE_SUFFIX}}", suffix)
    html = html.replace("{{SESSION_ID}}", _html_escape(session_id))
    return _with_csp(HTMLResponse(html))


def _serve_participant_app(session_id: str) -> HTMLResponse | FileResponse:
    """Serve the participant SPA for the LIVE session, or the read-only ended view
    for a registry-valid recent-PAST id (talk variant for talk sessions)."""
    if not _is_active_session(session_id):
        return _serve_ended_session_page(session_id)
    if state.session_type == "talk":
        return _serve_html_with_otel("static/talk.html", service_name="Talk")
    return _serve_html_with_otel("static/participant.html", service_name="Participant")


@participant_router.get("/", response_class=HTMLResponse, dependencies=[Depends(rate_limit_probe)])
async def participant_page(session_id: str):
    return _serve_participant_app(session_id)


@participant_router.get("/notes-print", response_class=HTMLResponse)
async def notes_print_page(session_id: str):
    """Standalone read-only session notes page (formerly served at /<session>/notes)."""
    # A past session has no live notes to fetch — steer it to the ended view too.
    if not _is_active_session(session_id):
        return _serve_ended_session_page(session_id)
    return _with_csp(FileResponse("static/notes.html"))


@participant_router.get("/{tab}", response_class=HTMLResponse, dependencies=[Depends(rate_limit_probe)])
async def participant_tab_page(session_id: str, tab: str):
    """Serve the participant SPA for a deep-linked tab (e.g. /<session>/notes)."""
    if tab not in _PARTICIPANT_TAB_SLUGS:
        raise HTTPException(status_code=404, detail="Unknown tab")
    return _serve_participant_app(session_id)


