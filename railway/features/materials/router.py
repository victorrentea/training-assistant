"""On-demand session materials zip for participants who cannot reach Google Drive.

This is NOT the materials mirror removed in dc1228ea: no background sync, no
per-file upsert/delete endpoints, and `materials/` is never mirrored. The
daemon builds one archive of the session folder when a participant asks, and
Railway caches it briefly.
"""
import asyncio
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from railway.features.ws.daemon_protocol import MSG_BUILD_MATERIALS_ZIP, push_to_daemon
from railway.shared.auth import require_host_auth
from railway.shared.state import state

router = APIRouter()  # daemon-facing, host auth
public_router = APIRouter()  # participant-facing, mounted under /{session_id}

logger = logging.getLogger(__name__)

MAX_ZIP_BYTES = 25 * 1024 * 1024
CACHE_TTL_S = 60.0
BUILD_TIMEOUT_S = 20.0
MATERIALS_DIR = Path(".server-data") / "materials"
DEFAULT_ZIP_NAME = "session-materials.zip"

# Resolves to None on success or to the daemon's error message on failure.
# Never rejected — a rejected Future whose waiter already timed out produces
# "Future exception was never retrieved" noise in the logs.
_pending_build: asyncio.Future | None = None
_built_at: float = 0.0
_zip_filename: str = DEFAULT_ZIP_NAME


class MaterialsZipUploadResponse(BaseModel):
    ok: bool
    size: int = 0
    filename: str = ""


def reset_materials_cache() -> None:
    """Test helper: drop cached archive and in-flight build state."""
    global _pending_build, _built_at, _zip_filename
    _pending_build = None
    _built_at = 0.0
    _zip_filename = DEFAULT_ZIP_NAME
    if MATERIALS_DIR.exists():
        for stale in MATERIALS_DIR.glob("*.zip"):
            stale.unlink(missing_ok=True)


def expire_cache_for_test() -> None:
    """Test helper: keep the archive on disk but mark it stale."""
    global _built_at
    _built_at = 0.0


def resolve_pending_build(error: str | None) -> None:
    """Complete the in-flight build, if any."""
    global _pending_build
    if _pending_build is not None and not _pending_build.done():
        _pending_build.set_result(error)
    _pending_build = None


def _zip_path(session_id: str) -> Path:
    safe = (session_id or "nosession").strip() or "nosession"
    return MATERIALS_DIR / f"{safe}.zip"


def _cache_is_fresh() -> bool:
    return _built_at > 0.0 and (time.monotonic() - _built_at) < CACHE_TTL_S


async def request_build() -> str | None:
    """Ask the daemon to build and upload the zip. Returns an error message or None.

    Concurrent callers share one build — the same dedup shape as
    `_pending_refresh` in railway/features/slides/router.py.
    """
    global _pending_build
    if _pending_build is not None and not _pending_build.done():
        return await asyncio.wait_for(asyncio.shield(_pending_build), timeout=BUILD_TIMEOUT_S)

    loop = asyncio.get_running_loop()
    _pending_build = loop.create_future()
    pending = _pending_build
    sent = await push_to_daemon(
        {"type": MSG_BUILD_MATERIALS_ZIP, "session_id": state.session_id or ""}
    )
    if not sent:
        resolve_pending_build("Trainer not connected")
        return "Trainer not connected"
    return await asyncio.wait_for(asyncio.shield(pending), timeout=BUILD_TIMEOUT_S)


@public_router.get("/api/materials/zip", operation_id="get_materials_zip")
async def get_materials_zip():
    """Serve the session materials archive, rebuilding it when the cache is stale."""
    path = _zip_path(state.session_id or "")
    if not (path.exists() and _cache_is_fresh()):
        try:
            error = await request_build()
        except asyncio.TimeoutError:
            error = f"Build timed out after {BUILD_TIMEOUT_S:.0f}s"
        if error:
            # Stale is better than nothing: a participant clicking this button
            # usually has no working alternative.
            logger.warning("[materials] zip build failed: %s", error)

    if not path.exists():
        raise HTTPException(status_code=503, detail="Session materials are not available right now")

    return FileResponse(
        path=path,
        media_type="application/zip",
        filename=_zip_filename,
        headers={"Cache-Control": "no-cache"},
    )


@router.post(
    "/api/materials/zip/upload",
    response_model=MaterialsZipUploadResponse,
    dependencies=[Depends(require_host_auth)],
)
async def upload_materials_zip(
    session_id: str = Form(...),
    filename: str = Form(default=""),
    error: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    """Receive the archive (or a build error) from the daemon."""
    global _built_at, _zip_filename

    if error:
        resolve_pending_build(error)
        return MaterialsZipUploadResponse(ok=False)

    if file is None:
        raise HTTPException(status_code=422, detail="file or error is required")

    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _zip_path(session_id)
    tmp = dest.with_suffix(".zip.part")
    total = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ZIP_BYTES:
                    out.close()
                    tmp.unlink(missing_ok=True)
                    raise HTTPException(
                        413, f"Zip too large (max {MAX_ZIP_BYTES // (1024 * 1024)}MB)"
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(500, "Zip upload failed") from exc

    if total == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Empty zip")

    tmp.replace(dest)  # atomic swap so a concurrent GET never sees a partial file
    _zip_filename = filename or DEFAULT_ZIP_NAME
    _built_at = time.monotonic()
    resolve_pending_build(None)
    logger.info("[materials] ↓ received zip %s (%d bytes)", _zip_filename, total)
    return MaterialsZipUploadResponse(ok=True, size=total, filename=_zip_filename)
