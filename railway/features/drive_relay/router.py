"""HTTP surface of the Drive relay.

Session-independent and daemon-independent by construction: nothing here imports
session state or the daemon WebSocket, so it answers while the trainer's laptop
is closed.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from railway.features.drive_relay import drive_client, ownership, tree
from railway.features.drive_relay.drive_client import DriveError, DriveFile
from railway.features.drive_relay.link_parser import InvalidDriveLink, parse_drive_url
from railway.features.drive_relay.tree import TransferPlan
from railway.shared.rate_limit import rate_limit_probe

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
