"""The session wiki: a static Quartz site the daemon builds from the session's wiki/ vault.

The daemon uploads the built site as one zip; participants browse it from here as
plain files, so page views never reach the trainer's machine. Only the ACTIVE
session's site is served (the router is mounted behind require_active_session),
and publishing one session's site deletes every other session's, so a past
cohort's wiki can't be reached by a new one, or the other way round.
"""
import io
import logging
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from railway.shared.auth import require_host_auth

router = APIRouter()  # daemon-facing, host auth
public_router = APIRouter()  # participant-facing, mounted under /{session_id}

logger = logging.getLogger(__name__)

WIKI_DIR = Path(".server-data") / "wiki"
MAX_ZIP_BYTES = 40 * 1024 * 1024
MAX_UNPACKED_BYTES = 150 * 1024 * 1024


class WikiUploadResponse(BaseModel):
    ok: bool
    files: int = 0


def _site_dir(session_id: str) -> Path:
    return WIKI_DIR / session_id


def _safe_session_id(session_id: str) -> str:
    if not session_id or not session_id.isalnum():
        raise HTTPException(status_code=422, detail="Invalid session_id")
    return session_id


def _unpack(payload: bytes, dest: Path) -> int:
    """Extract a site zip into dest, refusing anything that escapes it (zip-slip) or balloons."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            raise HTTPException(413, "Wiki site too large")
        for member in members:
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts:
                raise HTTPException(400, f"Unsafe path in wiki zip: {member.filename}")
            target = dest.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
        return len(members)


@router.post(
    "/api/wiki/upload",
    response_model=WikiUploadResponse,
    dependencies=[Depends(require_host_auth)],
)
async def upload_wiki(session_id: str = Form(...), file: UploadFile = File(...)):
    """Replace the session's wiki site with the uploaded build, and drop every other session's."""
    session_id = _safe_session_id(session_id)
    payload = await file.read(MAX_ZIP_BYTES + 1)
    if len(payload) > MAX_ZIP_BYTES:
        raise HTTPException(413, f"Wiki zip too large (max {MAX_ZIP_BYTES // (1024 * 1024)}MB)")
    if not payload:
        raise HTTPException(400, "Empty wiki zip")

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    staging = WIKI_DIR / f".{session_id}.incoming"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        files = _unpack(payload, staging)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise HTTPException(400, "Not a zip file") from exc
    except HTTPException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    for old in WIKI_DIR.iterdir():
        if old != staging:
            shutil.rmtree(old, ignore_errors=True)
    staging.rename(_site_dir(session_id))
    logger.info("[wiki] ↓ received site for %s (%d files, %d bytes)", session_id, files, len(payload))
    return WikiUploadResponse(ok=True, files=files)


def _resolve(site: Path, path: str) -> Path | None:
    """Map a Quartz URL to its file: pages are linked without '.html', folders end in '/'."""
    rel = PurePosixPath(path)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    base = site.joinpath(*rel.parts)
    for candidate in (base, base.with_name(base.name + ".html"), base / "index.html"):
        if candidate.is_file():
            return candidate
    return None


@public_router.get("/wiki-site/{path:path}", include_in_schema=False)
async def get_wiki_file(session_id: str, path: str = ""):
    site = _site_dir(_safe_session_id(session_id))
    if not site.is_dir():
        raise HTTPException(status_code=404, detail="No wiki published for this session")
    target = _resolve(site, path)
    if target is None:
        not_found = site / "404.html"
        if not_found.is_file():
            return FileResponse(not_found, status_code=404, media_type="text/html")
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target, headers={"Cache-Control": "no-cache"})
