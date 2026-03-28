import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state

router = APIRouter()

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
UPLOAD_DIR = Path(".server-data") / "uploads"
CLEANUP_DELAY_SECONDS = 5 * 60  # 5 minutes after download


def _upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def _find_entry(file_id: int) -> tuple[str, dict] | None:
    for uuid, entries in state.uploaded_files.items():
        for entry in entries:
            if entry["id"] == file_id:
                return uuid, entry
    return None


async def _cleanup_after_delay(file_id: int):
    """Delete file from disk and state after CLEANUP_DELAY_SECONDS."""
    await asyncio.sleep(CLEANUP_DELAY_SECONDS)
    for uuid, entries in list(state.uploaded_files.items()):
        for entry in entries:
            if entry["id"] == file_id:
                Path(entry["disk_path"]).unlink(missing_ok=True)
                state.uploaded_files[uuid] = [e for e in entries if e["id"] != file_id]
                if not state.uploaded_files[uuid]:
                    del state.uploaded_files[uuid]
                await broadcast_state()
                return


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
        "downloaded_at": None,  # epoch seconds, set on first host download
    }
    state.uploaded_files.setdefault(uuid, []).append(entry)
    await broadcast_state()
    return {"ok": True, "id": file_id, "filename": filename, "size": total}


@router.get("/api/upload/{file_id}", dependencies=[Depends(require_host_auth)])
async def download_file(file_id: int):
    result = _find_entry(file_id)
    if not result:
        raise HTTPException(404, "File not found")
    uuid, entry = result
    path = Path(entry["disk_path"])
    if not path.exists():
        raise HTTPException(404, "File no longer available")
    # Mark as downloaded and schedule cleanup
    if entry["downloaded_at"] is None:
        entry["downloaded_at"] = time.time()
        asyncio.create_task(_cleanup_after_delay(file_id))
        # Broadcast so host UI shows the fade
        await broadcast_state()
    return FileResponse(
        path,
        filename=entry["filename"],
        media_type="application/octet-stream",
    )
