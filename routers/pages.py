from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from auth import require_host_auth

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def participant_page():
    return FileResponse("static/participant.html")


@router.get("/host", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_page():
    return FileResponse("static/host.html")
