"""HTTP surface of the Drive relay.

Session-independent and daemon-independent by construction: nothing here imports
session state or the daemon WebSocket, so it answers while the trainer's laptop
is closed.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from railway.features.drive_relay import drive_client, ownership, tree
from railway.features.drive_relay.drive_client import DriveError, DriveFile
from railway.features.drive_relay.link_parser import InvalidDriveLink, parse_drive_url
from railway.features.drive_relay.tree import PlannedEntry, TransferPlan
from railway.features.drive_relay.zip_stream import TransferCapExceeded, stream_zip
from railway.shared.rate_limit import rate_limit_drive_zip, rate_limit_probe

logger = logging.getLogger(__name__)

router = APIRouter()
page_router = APIRouter()

MAX_TRANSFER_BYTES = 500 * 1024 * 1024

BAD_LINK = "That doesn't look like a Google Drive link"
NOT_AVAILABLE = "This folder is not shared publicly, or the link is wrong"
DRIVE_DOWN = "Google Drive is not responding right now — please try again"
TOO_LARGE = (
    "This folder is larger than 500 MB — ask Victor to split it or send it another way"
)


class DrivePreviewResponse(BaseModel):
    name: str
    file_count: int
    total_bytes: int
    has_unsized_files: bool


def _load_root(url: str) -> DriveFile:
    try:
        file_id = parse_drive_url(url)
    except InvalidDriveLink:
        raise HTTPException(status_code=400, detail=BAD_LINK) from None

    try:
        root = drive_client.get_metadata(file_id)
    except DriveError as exc:
        if exc.status in (401, 403, 404):
            logger.info("[drive-relay] refused %s: Drive returned %s", file_id, exc.status)
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        logger.warning("[drive-relay] Drive error for %s: %s", file_id, exc)
        raise HTTPException(status_code=502, detail=DRIVE_DOWN) from None

    emails, permission_ids = ownership.configured_identity()
    if not ownership.is_owned_by_host(root, emails=emails, permission_ids=permission_ids):
        # Answers 404, not 403: matching only the message would still leave the status
        # code as an oracle, since 403 would fire solely for folders that are real,
        # public and owned by someone else. The log keeps the true reason; the trainer
        # himself pasting a folder he does not own gets this same misleading message —
        # an accepted cost of closing the oracle.
        logger.warning("[drive-relay] refused %s: not owned by the configured trainer", file_id)
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE)

    return root


def _resolve_plan_sync(url: str) -> tuple[DriveFile, TransferPlan]:
    root = _load_root(url)
    try:
        plan = tree.build_plan(root)
    except DriveError as exc:
        logger.warning("[drive-relay] listing failed for %s: %s", root.id, exc)
        raise HTTPException(status_code=502, detail=DRIVE_DOWN) from None

    if plan.known_bytes > MAX_TRANSFER_BYTES:
        raise HTTPException(status_code=413, detail=TOO_LARGE)
    return root, plan


async def resolve_plan(url: str) -> tuple[DriveFile, TransferPlan]:
    """Validate the link and plan the transfer, off the event loop.

    Drive calls go through blocking urllib (the same stdlib-only approach as
    railway/features/slides/cache.py), so they must not run on the loop.
    """
    return await run_in_threadpool(_resolve_plan_sync, url)


@router.get(
    "/api/drive/preview",
    response_model=DrivePreviewResponse,
    operation_id="get_drive_preview",
    dependencies=[Depends(rate_limit_probe)],
)
async def get_drive_preview(url: str) -> DrivePreviewResponse:
    """Validate a pasted Drive link and describe what a download would contain."""
    _, plan = await resolve_plan(url)
    return DrivePreviewResponse(
        name=plan.root_name,
        file_count=len(plan.entries),
        total_bytes=plan.known_bytes,
        has_unsized_files=plan.has_unsized_files,
    )


# Strips C0 control characters (including \r and \n) from a header value before
# it is ever assembled. A raw newline in Content-Disposition is a response-
# splitting vector, and TransferPlan.root_name comes straight from a
# Drive-supplied folder name — it is not sanitised for header safety upstream.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _content_disposition(filename: str) -> str:
    """RFC 5987 disposition so unicode course names survive the header.

    ``filename`` may contain anything a Drive folder/file name can contain,
    including quotes and control characters. Control characters are stripped
    up front so neither header half can smuggle a newline; the surviving
    quote character is neutralised in the ASCII fallback, and
    ``urllib.parse.quote`` percent-encodes everything (quotes included) in the
    UTF-8 half.
    """
    safe = _CONTROL_CHARS.sub("", filename)
    ascii_fallback = safe.encode("ascii", "replace").decode("ascii").replace('"', "_")
    quoted = urllib.parse.quote(safe, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"


def _guarded_chunks(chunks: Iterator[bytes], *, context: str) -> Iterator[bytes]:
    """Relay a Drive byte stream, logging and cutting it off on failure or overrun.

    Shared tail behaviour for both the zip path and the single-file path: by
    the time either one is running, headers are already on the wire, so a
    failure can only end the stream early — it can never turn into a status
    code. Both paths therefore log the same way and simply stop.
    """
    try:
        yield from chunks
    except TransferCapExceeded:
        # Reaching here means the pre-check under-counted, which happens when
        # the file(s) involved are Google-native (they report no size).
        logger.warning("[drive-relay] transfer cap hit mid-stream for %s", context)
    except DriveError as exc:
        logger.warning("[drive-relay] download failed mid-stream for %s: %s", context, exc)


def _capped(chunks: Iterator[bytes], max_bytes: int) -> Iterator[bytes]:
    """Cut a byte stream off once it passes ``max_bytes``.

    The zip path gets this for free from zip_stream.stream_zip's own running
    counter. The single-file path streams drive_client.open_download directly
    with no counter of its own — without this, a Google-native file (which
    always reports size=None, so the pre-check in resolve_plan can never catch
    it) would stream unbounded.
    """
    written = 0
    for chunk in chunks:
        written += len(chunk)
        if written > max_bytes:
            raise TransferCapExceeded(f"Transfer exceeded {max_bytes} bytes")
        yield chunk


def _archive_chunks(plan: TransferPlan) -> Iterator[bytes]:
    """Yield the archive, downloading each file only as the client consumes it."""
    entries = ((entry.archive_path, drive_client.open_download(entry.file))
               for entry in plan.entries)
    yield from _guarded_chunks(
        stream_zip(entries, max_bytes=MAX_TRANSFER_BYTES), context=plan.root_name
    )


def _single_file_chunks(entry: PlannedEntry) -> Iterator[bytes]:
    """Yield one file's bytes, capped and guarded exactly like the zip path."""
    yield from _guarded_chunks(
        _capped(drive_client.open_download(entry.file), MAX_TRANSFER_BYTES),
        context=entry.archive_path,
    )


@router.get(
    "/api/drive/zip",
    operation_id="get_drive_zip",
    response_class=StreamingResponse,
    dependencies=[Depends(rate_limit_drive_zip)],
)
async def get_drive_zip(url: str) -> StreamingResponse:
    """Stream the pasted Drive folder as a zip. A single file streams as itself.

    Every byte is relayed through this server — we follow Drive's own redirects
    inside drive_client and never hand one to the browser, because the
    participants this exists for cannot reach Google at all.
    """
    root, plan = await resolve_plan(url)

    if not drive_client.is_folder(root):
        entry = plan.entries[0]
        logger.info("[drive-relay] ↓ single file %s (%s bytes)", entry.archive_path,
                    entry.file.size)
        return StreamingResponse(
            _single_file_chunks(entry),
            media_type=entry.file.mime_type or "application/octet-stream",
            headers={
                "Content-Disposition": _content_disposition(entry.archive_path),
                "Cache-Control": "no-store",
            },
        )

    logger.info("[drive-relay] ↓ zip '%s' (%d files, %d known bytes)",
                plan.root_name, len(plan.entries), plan.known_bytes)
    # root_name comes straight from Drive and may contain path separators
    # ("/", "\\") or dot runs — flatten it with the same helper tree.py uses
    # for archive path segments so the zip's own filename can't smuggle either.
    zip_name = f"{tree._safe_name(plan.root_name)}.zip"
    return StreamingResponse(
        _archive_chunks(plan),
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(zip_name),
            "Cache-Control": "no-store",
        },
    )
