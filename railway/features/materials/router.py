"""On-demand session materials zip for participants who cannot reach Google Drive.

This is NOT the materials mirror removed in dc1228ea: no background sync, no
per-file upsert/delete endpoints, and `materials/` is never mirrored. The
daemon builds one archive of the session folder when a participant asks, and
Railway caches it briefly.
"""
import asyncio
import json
import logging
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from railway.features.slides.cache import CACHE_DIR as SLIDES_CACHE_DIR
from railway.features.slides.cache import do_download
from railway.features.ws.daemon_protocol import MSG_BUILD_MATERIALS_ZIP, push_to_daemon
from railway.shared.auth import require_host_auth
from railway.shared.state import state

router = APIRouter()  # daemon-facing, host auth
public_router = APIRouter()  # participant-facing, mounted under /{session_id}

logger = logging.getLogger(__name__)

MAX_ZIP_BYTES = 25 * 1024 * 1024
# The decks are added here, after the daemon's upload, so they never count
# against MAX_ZIP_BYTES — but a session that flipped through six big decks
# still must not produce a 200 MB download.
MAX_ZIP_WITH_DECKS_BYTES = 100 * 1024 * 1024
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
    decks: list[str] = []


class ZipDeck(BaseModel):
    """A deck the daemon saw on screen; mirrors daemon/materials/viewed_decks.py."""

    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    filename: str = Field(pattern=r"^[^/\\]+\.pdf$")
    drive_export_url: str = ""


_background_downloads: set[asyncio.Task] = set()


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


def _parse_decks(raw: str) -> list[ZipDeck]:
    """Decode the daemon's deck list, dropping entries that fail validation.

    The decks are an extra: a bad one must cost only itself, never the session
    archive the participant is waiting for.
    """
    try:
        entries = json.loads(raw or "[]")
    except ValueError:
        logger.warning("[materials] ignoring malformed decks field: %.200s", raw)
        return []
    if not isinstance(entries, list):
        logger.warning("[materials] ignoring decks field that is not a list: %.200s", raw)
        return []
    decks: list[ZipDeck] = []
    for entry in entries:
        try:
            decks.append(ZipDeck.model_validate(entry))
        except ValidationError:
            logger.warning("[materials] ignoring invalid deck: %.200s", entry)
    return decks


def _append_cached_decks(zip_path: Path, decks: list[ZipDeck]) -> tuple[list[str], list[ZipDeck]]:
    """Add each deck's cached PDF to the archive as slides/<filename>, most-viewed first.

    Returns (added filenames, decks with no cached PDF yet). A deck that would
    push the archive past MAX_ZIP_WITH_DECKS_BYTES is left out.
    """
    added: list[str] = []
    uncached: list[ZipDeck] = []
    total = zip_path.stat().st_size
    with zipfile.ZipFile(zip_path, "a") as archive:
        for deck in decks:
            pdf = SLIDES_CACHE_DIR / f"{deck.slug}.pdf"
            if not pdf.is_file():
                uncached.append(deck)
                continue
            size = pdf.stat().st_size
            if total + size > MAX_ZIP_WITH_DECKS_BYTES:
                logger.warning("[materials] deck %s left out: zip would exceed %d MB",
                               deck.filename, MAX_ZIP_WITH_DECKS_BYTES // (1024 * 1024))
                continue
            # PDFs are already compressed; deflating them again only costs CPU.
            archive.write(pdf, arcname=f"slides/{deck.filename}", compress_type=zipfile.ZIP_STORED)
            total += size
            added.append(deck.filename)
    return added, uncached


def _warm_slides_cache(decks: list[ZipDeck]) -> None:
    """Fetch uncached decks in the background, so the next build (after CACHE_TTL_S) has them."""
    for deck in decks:
        if not deck.drive_export_url:
            continue
        if (state.slides_updated.get(deck.slug) or {}).get("status") == "downloading":
            continue
        task = asyncio.create_task(do_download(deck.slug, deck.drive_export_url))
        _background_downloads.add(task)
        task.add_done_callback(_background_downloads.discard)
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # logged by do_download


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
    decks: str = Form(default="[]"),
    file: UploadFile | None = File(default=None),
):
    """Receive the archive (or a build error) from the daemon, then add the viewed decks' PDFs."""
    global _built_at, _zip_filename

    if error:
        resolve_pending_build(error)
        return MaterialsZipUploadResponse(ok=False)

    wanted_decks = _parse_decks(decks)

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

    added: list[str] = []
    if wanted_decks:
        try:
            added, uncached = await asyncio.to_thread(_append_cached_decks, tmp, wanted_decks)
        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("[materials] could not add decks to the zip: %s", exc)
            uncached = []
        _warm_slides_cache(uncached)

    tmp.replace(dest)  # atomic swap so a concurrent GET never sees a partial file
    _zip_filename = filename or DEFAULT_ZIP_NAME
    _built_at = time.monotonic()
    resolve_pending_build(None)
    logger.info("[materials] ↓ received zip %s (%d bytes), added decks: %s",
                _zip_filename, total, ", ".join(added) or "none")
    return MaterialsZipUploadResponse(ok=True, size=total, filename=_zip_filename, decks=added)
