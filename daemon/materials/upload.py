"""Handle Railway's build_materials_zip request: zip the session folder and upload it.

Not a background mirror (see dc1228ea) — this only runs when Railway asks,
which only happens when a participant clicks the download button.
"""
from __future__ import annotations

import base64
import ssl
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from daemon import log
from daemon.materials.zip_builder import (
    ZipTooLargeError,
    build_session_zip,
    session_zip_filename,
)

_UPLOAD_PATH = "/api/materials/zip/upload"
_TIMEOUT_S = 30


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def build_multipart(
    fields: dict[str, str], file_part: tuple[str, bytes] | None
) -> tuple[bytes, str]:
    """Encode a multipart/form-data body. Returns (body, boundary)."""
    boundary = f"----materials-zip-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    if file_part is not None:
        filename, payload = file_part
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: application/zip\r\n\r\n"
            ).encode()
        )
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def _post_multipart(url: str, body: bytes, boundary: str, config) -> None:
    token = base64.b64encode(
        f"{config.host_username}:{config.host_password}".encode()
    ).decode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S, context=_ssl_context()):
        pass


def handle_build_materials_zip(data: dict, config) -> None:
    """Build the session zip and POST it to Railway; report failures the same way."""
    session_id = str(data.get("session_id") or "")
    folder: Path | None = getattr(config, "session_folder", None)
    url = f"{config.server_url}{_UPLOAD_PATH}"

    fields: dict[str, str] = {"session_id": session_id}
    file_part: tuple[str, bytes] | None = None

    try:
        if folder is None:
            raise FileNotFoundError("No active session folder")
        payload = build_session_zip(folder)
        filename = session_zip_filename(folder)
        fields["filename"] = filename
        file_part = (filename, payload)
        log.info("materials", f"↑ built session zip {filename} ({len(payload)} bytes)")
    except (FileNotFoundError, ZipTooLargeError, OSError) as exc:
        fields["error"] = str(exc)
        log.error("materials", f"Session zip build failed: {exc}")

    body, boundary = build_multipart(fields, file_part)
    try:
        _post_multipart(url, body, boundary, config)
    except (urllib.error.URLError, OSError) as exc:
        log.error("materials", f"Session zip upload failed: {exc}")
