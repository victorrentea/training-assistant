import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel as _BaseModel

from railway.shared.auth import require_host_auth
from railway.shared.state import state

router = APIRouter()  # host-auth endpoints
public_router = APIRouter()  # participant-facing endpoints (upload), mounted under session prefix

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB
UPLOAD_DIR = Path(".server-data") / "uploads"


def _upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def _find_entry(file_id: int) -> tuple[str, dict] | None:
    for uuid, entries in state.uploaded_files.items():
        for entry in entries:
            if entry["id"] == file_id:
                return uuid, entry
    return None


@public_router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    uuid: str = Form(...),
):
    if not uuid or uuid.startswith("__"):
        raise HTTPException(400, "Invalid participant UUID")
    if uuid not in state.participant_names and uuid not in state.participants:
        raise HTTPException(400, "Unknown participant")

    filename = (file.filename or "file").strip()
    if not filename:
        filename = "file"
    # Sanitize filename
    filename = Path(filename).name  # strip any directory components
    if not filename:
        filename = "file"

    # Stream to temp file with size check (never load full file in memory)
    state.upload_next_id += 1
    file_id = state.upload_next_id
    dest = _upload_dir() / f"{file_id}_{filename}"

    total = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(64 * 1024)  # 64KB chunks
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"File too large (max {MAX_UPLOAD_SIZE // (1024*1024)}MB)")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, "Upload failed") from exc

    if total == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file")

    entry = {
        "id": file_id,
        "filename": filename,
        "size": total,
        "disk_path": "",  # filled by daemon ack
        "railway_path": str(dest),  # temp file on Railway
        "downloaded_at": None,
    }
    state.uploaded_files.setdefault(uuid, []).append(entry)

    # Notify daemon to download the file
    from railway.features.ws.daemon_protocol import MSG_FILE_READY_FOR_DOWNLOAD, push_to_daemon
    asyncio.create_task(push_to_daemon({
        "type": MSG_FILE_READY_FOR_DOWNLOAD,
        "file_id": file_id,
        "uuid": uuid,
        "filename": filename,
        "size": total,
        "session_id": state.session_id or "",
    }))

    return {"ok": True, "id": file_id, "filename": filename, "size": total}


class _AckBody(_BaseModel):
    disk_path: str


@router.get("/upload/{file_id}", dependencies=[Depends(require_host_auth)])
async def download_for_daemon(file_id: int):
    """Daemon fetches uploaded temp file before persisting it locally."""
    result = _find_entry(file_id)
    if not result:
        raise HTTPException(404, "File not found")
    _, entry = result
    railway_path = Path(entry.get("railway_path", ""))
    if not railway_path.exists():
        raise HTTPException(404, "File content missing")
    filename = entry.get("filename") or railway_path.name
    return FileResponse(path=railway_path, filename=filename, media_type="application/octet-stream")


@router.post("/upload/{file_id}/ack", dependencies=[Depends(require_host_auth)])
async def ack_upload(file_id: int, body: _AckBody):
    result = _find_entry(file_id)
    if not result:
        raise HTTPException(404, "File not found")
    _, entry = result
    entry["disk_path"] = body.disk_path
    entry["downloaded_at"] = time.time()
    # Delete temp file from Railway
    railway_path = Path(entry.get("railway_path", ""))
    if railway_path.exists():
        railway_path.unlink(missing_ok=True)
    return {"ok": True}
