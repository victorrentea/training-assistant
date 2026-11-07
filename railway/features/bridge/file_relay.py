"""Files from the phone to the Mac, when they share no network.

Only ciphertext passes through here: the sender seals each file with a key this server never
sees. Files stay in memory for fifteen minutes at most and are never logged. A redeploy loses
at most a file nobody picked up, and the phone then keeps it.

The phone polls `state` to learn the Mac took the file, which is what the Mac's DELETE says.

Auth: the bridge's shared token, as `X-Bridge-Token`.
"""
import time
from dataclasses import dataclass

from fastapi import APIRouter, Header, HTTPException, Path, Request, Response

from railway.features.bridge.phone_battery import _check

router = APIRouter()

TTL_S = 900
MAX_FILE = 40 * 1024 * 1024
MAX_TOTAL = 120 * 1024 * 1024

FileId = Path(pattern=r"^[0-9a-f]{32}$")


@dataclass
class _File:
    body: bytes | None
    at: float


_files: dict[str, _File] = {}


def _forget_old() -> None:
    now = time.time()
    for file_id in [i for i, f in _files.items() if now - f.at > TTL_S]:
        del _files[file_id]


def _held() -> int:
    return sum(len(f.body) for f in _files.values() if f.body is not None)


@router.put("/api/file/{file_id}")
async def put_file(request: Request, file_id: str = FileId, x_bridge_token: str | None = Header(default=None)) -> dict:
    _check(x_bridge_token)
    _forget_old()
    room = min(MAX_FILE, MAX_TOTAL - _held())
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > room:
            raise HTTPException(status_code=413, detail="too large")
    _files[file_id] = _File(bytes(body), time.time())
    return {"size": len(body)}


@router.get("/api/file/{file_id}")
def get_file(file_id: str = FileId, x_bridge_token: str | None = Header(default=None)) -> Response:
    _check(x_bridge_token)
    _forget_old()
    file = _files.get(file_id)
    if file is None or file.body is None:
        raise HTTPException(status_code=404, detail="not found")
    return Response(content=file.body, media_type="application/octet-stream")


@router.get("/api/file/{file_id}/state")
def file_state(file_id: str = FileId, x_bridge_token: str | None = Header(default=None)) -> dict:
    """`waiting`, `taken` by the Mac, or `gone`: expired, or lost to a redeploy."""
    _check(x_bridge_token)
    _forget_old()
    file = _files.get(file_id)
    if file is None:
        return {"state": "gone"}
    return {"state": "waiting" if file.body is not None else "taken"}


@router.delete("/api/file/{file_id}")
def take_file(file_id: str = FileId, x_bridge_token: str | None = Header(default=None)) -> dict:
    _check(x_bridge_token)
    _files[file_id] = _File(None, time.time())
    return {"state": "taken"}
