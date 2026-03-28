import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state

router = APIRouter()

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
UPLOAD_DIR = Path(".server-data") / "uploads"


def _upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    uuid: str = Form(...),
):
    if not uuid or uuid.startswith("__"):
        raise HTTPException(400, "Invalid participant UUID")
    if uuid not in state.participant_names:
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
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, "Upload failed")

    if total == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file")

    entry = {
        "id": file_id,
        "filename": filename,
        "size": total,
        "disk_path": str(dest),
    }
    state.uploaded_files.setdefault(uuid, []).append(entry)
    await broadcast_state()
    return {"ok": True, "id": file_id, "filename": filename, "size": total}


@router.get("/api/upload/{file_id}", dependencies=[Depends(require_host_auth)])
async def download_file(file_id: int):
    # Find the entry
    for uuid, entries in state.uploaded_files.items():
        for entry in entries:
            if entry["id"] == file_id:
                path = Path(entry["disk_path"])
                if not path.exists():
                    raise HTTPException(404, "File no longer available")
                return FileResponse(
                    path,
                    filename=entry["filename"],
                    media_type="application/octet-stream",
                )
    raise HTTPException(404, "File not found")
