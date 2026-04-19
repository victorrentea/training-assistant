import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from railway.shared.auth import get_host_cookie_token, require_host_auth
from railway.shared.state import state

landing_router = APIRouter()
host_router = APIRouter()
participant_router = APIRouter()

_OTEL_ENABLED = bool(os.environ.get("OTEL_TRACES_FILE"))


def _serve_html_with_otel(path: str, service_name: str = "Browser") -> HTMLResponse | FileResponse:
    """Serve an HTML file, injecting OTel meta tags when telemetry is active."""
    if not _OTEL_ENABLED:
        return FileResponse(path)
    html = open(path, encoding="utf-8").read()
    meta = (
        f'  <meta name="otel-endpoint" content="/api/telemetry/spans">\n'
        f'  <meta name="otel-service-name" content="{service_name}">\n'
    )
    html = html.replace("</head>", f"{meta}</head>", 1)
    return HTMLResponse(html)


@landing_router.get("/", response_class=HTMLResponse)
async def landing_page():
    return FileResponse("static/landing.html")


@landing_router.get("/new", response_class=HTMLResponse)
async def new_page():
    return FileResponse("static/new/code.html")


@host_router.get("/host/", response_class=HTMLResponse)
async def host_landing_redirect():
    return RedirectResponse(url="/host", status_code=301)


@host_router.get("/host", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_landing():
    response = FileResponse("static/host-landing.html")
    response.set_cookie("is_host", get_host_cookie_token(), path="/", samesite="strict", httponly=True)
    return response


@host_router.get("/host/{session_id}", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_page(session_id: str):
    response = _serve_html_with_otel("static/host.html", service_name="Host")
    if isinstance(response, FileResponse):
        response.set_cookie("is_host", get_host_cookie_token(), path="/", samesite="strict", httponly=True)
    else:
        response.set_cookie("is_host", get_host_cookie_token(), path="/", samesite="strict", httponly=True)
    return response


@participant_router.get("/", response_class=HTMLResponse)
async def participant_page():
    if state.session_type == "talk":
        return _serve_html_with_otel("static/talk.html", service_name="Talk")
    return _serve_html_with_otel("static/participant.html", service_name="Participant")


@participant_router.get("/notes", response_class=HTMLResponse)
async def notes_page():
    return FileResponse("static/notes.html")


