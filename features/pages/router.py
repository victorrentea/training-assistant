from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse, FileResponse

from core.auth import get_host_cookie_token, require_host_auth
from core.state import state

landing_router = APIRouter()
host_router = APIRouter()
participant_router = APIRouter()


@landing_router.get("/", response_class=HTMLResponse)
async def landing_page():
    return FileResponse("static/landing.html")


@host_router.get("/host", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_landing():
    response = FileResponse("static/host-landing.html")
    response.set_cookie("is_host", get_host_cookie_token(), path="/", samesite="strict", httponly=True)
    return response


@host_router.get("/host/{session_id}", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_page(session_id: str):
    response = FileResponse("static/host.html")
    response.set_cookie("is_host", get_host_cookie_token(), path="/", samesite="strict", httponly=True)
    return response


@participant_router.get("/", response_class=HTMLResponse)
async def participant_page():
    return FileResponse("static/participant.html")


@participant_router.get("/notes", response_class=HTMLResponse)
async def notes_page():
    return FileResponse("static/notes.html")


@participant_router.get("/quiz", response_class=HTMLResponse)
async def quiz_history_page():
    content = state.quiz_md_content.strip()
    if not content:
        body = "<p style='color:#888'>No questions have been asked yet in this session.</p>"
    else:
        # Convert simple markdown to HTML (## headings + - list items)
        html_lines = []
        for line in content.splitlines():
            if line.startswith("## "):
                html_lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("- "):
                html_lines.append(f"<li>{line[2:]}</li>")
            else:
                html_lines.append(f"<p>{line}</p>" if line.strip() else "")
        body = "\n".join(html_lines)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Quiz History</title>
  <style>
    body {{ font-family: sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; background: #1a1a2e; color: #e0e0e0; }}
    h1 {{ color: #a0c4ff; }}
    h2 {{ color: #c3f0ca; margin-top: 2rem; }}
    li {{ list-style: none; padding: 0.3rem 0; font-size: 1rem; }}
    p {{ margin: 0; }}
  </style>
</head>
<body>
  <h1>Quiz History</h1>
  {body}
</body>
</html>""")
