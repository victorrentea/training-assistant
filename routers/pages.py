from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def participant_page():
    return FileResponse("static/participant.html")


@router.get("/host", response_class=HTMLResponse)
async def host_page():
    return FileResponse("static/host.html")
