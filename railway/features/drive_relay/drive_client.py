"""Google Drive API v3 over stdlib urllib, authenticated with a plain API key.

The only module in this package that knows Google exists. API-key auth is enough
because every folder we serve is shared "anyone with the link" — see the spec.

urllib follows redirects on its own, which is load-bearing: large-file downloads
redirect to drive.usercontent.google.com and we must follow that *here*, on the
server, so the participant's browser never talks to Google.
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TypeVar

_T = TypeVar("_T")

# Anything that means "the connection to Drive misbehaved," as opposed to Drive
# giving us a clean HTTP status. Covers urlopen() itself (URLError, socket
# timeouts via OSError) and body reads after a successful connect
# (http.client.IncompleteRead is an HTTPException, not an OSError).
_CONNECTION_ERRORS = (urllib.error.URLError, OSError, http.client.HTTPException)

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
NATIVE_MIME_PREFIX = "application/vnd.google-apps."
NATIVE_EXPORT_MIME = "application/pdf"

_DEFAULT_BASE_URL = "https://www.googleapis.com/drive/v3"
_TIMEOUT_S = 30
_CHUNK_BYTES = 64 * 1024
_PAGE_SIZE = "1000"

_FILE_FIELDS = (
    "id,name,mimeType,size,owners(emailAddress,permissionId,displayName),"
    "shortcutDetails(targetId)"
)


@dataclass(frozen=True)
class DriveOwner:
    email: str
    permission_id: str
    display_name: str


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None
    owners: tuple[DriveOwner, ...]
    shortcut_target_id: str | None


class DriveError(RuntimeError):
    """A Drive call failed. ``status`` is the HTTP status we should surface."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _base_url() -> str:
    return os.environ.get("DRIVE_API_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = os.environ.get("GOOGLE_DRIVE_API_KEY", "").strip()
    if not key:
        raise DriveError(503, "GOOGLE_DRIVE_API_KEY is not configured")
    return key


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _build_url(path: str, params: dict) -> str:
    query = urllib.parse.urlencode(dict(params, key=_api_key()))
    return f"{_base_url()}{path}?{query}"


def _guarded(func: Callable[..., _T], *args, **kwargs) -> _T:
    """Run a urllib/http.client call, translating its failures into DriveError.

    Used both for the initial `urlopen()` and for the body reads that happen
    afterwards (`response.read(...)`) — a dropped connection mid-download is
    just as much a DriveError(502) as one that never connected at all, and
    callers (the router) must only ever have to catch one exception type.
    """
    try:
        return func(*args, **kwargs)
    except urllib.error.HTTPError as exc:
        raise DriveError(exc.code, f"Drive returned {exc.code}") from exc
    except _CONNECTION_ERRORS as exc:
        raise DriveError(502, f"Drive is unreachable: {exc}") from exc


def _open(url: str):
    request = urllib.request.Request(url, method="GET")
    return _guarded(urllib.request.urlopen, request, context=_ssl_ctx(), timeout=_TIMEOUT_S)


def _get_json(path: str, params: dict) -> dict:
    with _open(_build_url(path, params)) as response:
        raw = _guarded(response.read)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DriveError(502, f"Drive returned malformed JSON: {exc}") from exc


def _to_file(raw: dict) -> DriveFile:
    owners = tuple(
        DriveOwner(
            email=(owner.get("emailAddress") or "").strip().lower(),
            permission_id=(owner.get("permissionId") or "").strip(),
            display_name=(owner.get("displayName") or "").strip(),
        )
        for owner in raw.get("owners", [])
    )
    raw_size = raw.get("size")
    return DriveFile(
        id=raw.get("id", ""),
        name=raw.get("name", "") or "untitled",
        mime_type=raw.get("mimeType", ""),
        size=int(raw_size) if raw_size is not None else None,
        owners=owners,
        shortcut_target_id=(raw.get("shortcutDetails") or {}).get("targetId"),
    )


def is_folder(file: DriveFile) -> bool:
    return file.mime_type == FOLDER_MIME


def is_shortcut(file: DriveFile) -> bool:
    return file.mime_type == SHORTCUT_MIME


def is_native(file: DriveFile) -> bool:
    """True for Docs/Sheets/Slides — they have no bytes and must be exported."""
    return (
        file.mime_type.startswith(NATIVE_MIME_PREFIX)
        and not is_folder(file)
        and not is_shortcut(file)
    )


def archive_name(file: DriveFile) -> str:
    """The filename this file should carry inside the archive."""
    if is_native(file) and not file.name.lower().endswith(".pdf"):
        return f"{file.name}.pdf"
    return file.name


def get_metadata(file_id: str) -> DriveFile:
    path = f"/files/{urllib.parse.quote(file_id, safe='')}"
    return _to_file(_get_json(path, {"fields": _FILE_FIELDS, "supportsAllDrives": "true"}))


def list_children(folder_id: str) -> list[DriveFile]:
    """Every non-trashed direct child of ``folder_id``, across all result pages."""
    children: list[DriveFile] = []
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": f"nextPageToken,files({_FILE_FIELDS})",
            "pageSize": _PAGE_SIZE,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _get_json("/files", params)
        children.extend(_to_file(raw) for raw in payload.get("files", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return children


def open_download(file: DriveFile) -> Iterator[bytes]:
    """Yield the file's bytes, exporting Google-native files to PDF."""
    quoted = urllib.parse.quote(file.id, safe="")
    if is_native(file):
        url = _build_url(f"/files/{quoted}/export", {"mimeType": NATIVE_EXPORT_MIME})
    else:
        url = _build_url(f"/files/{quoted}", {"alt": "media", "supportsAllDrives": "true"})

    with _open(url) as response:
        while True:
            chunk = _guarded(response.read, _CHUNK_BYTES)
            if not chunk:
                return
            yield chunk
