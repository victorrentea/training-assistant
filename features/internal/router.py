"""Internal endpoints for daemon → backend file management."""
import base64
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_host_auth

router = APIRouter(prefix="/internal", dependencies=[Depends(require_host_auth)])
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

_ALLOWED_EXTENSIONS = {".html", ".js", ".css", ".png", ".jpg", ".svg", ".ico", ".json", ".woff", ".woff2", ".ttf"}
_EXCLUDED_FILES = {"version.js", "deploy-info.json", "work-hours.js"}
_MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB decoded


class UploadStaticRequest(BaseModel):
    path: str
    content_b64: str


class DeleteStaticRequest(BaseModel):
    path: str


def _validate_path(rel_path: str) -> Path:
    clean = rel_path.strip().replace("\\", "/")
    if ".." in clean or clean.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    resolved = (_STATIC_DIR / clean).resolve()
    if not str(resolved).startswith(str(_STATIC_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal denied")
    if resolved.name in _EXCLUDED_FILES:
        raise HTTPException(status_code=400, detail=f"Cannot overwrite {resolved.name}")
    suffix = resolved.suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extension {suffix} not allowed")
    return resolved


@router.post("/upload-static")
async def upload_static(req: UploadStaticRequest):
    target = _validate_path(req.path)
    try:
        content = base64.b64decode(req.content_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 content")
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large ({len(content)} bytes, max {_MAX_UPLOAD_SIZE})")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    logger.info("Static file uploaded: %s (%d bytes)", req.path, len(content))
    return {"status": "ok", "path": req.path, "size": len(content)}


@router.post("/delete-static")
async def delete_static(req: DeleteStaticRequest):
    target = _validate_path(req.path)
    if not target.exists():
        return {"status": "ok", "action": "not_found"}
    target.unlink()
    logger.info("Static file deleted: %s", req.path)
    return {"status": "ok", "action": "deleted"}
