"""The anti-abuse gate: only folders owned by the trainer may be relayed.

Without this, an endpoint that zips any public Drive folder is a free download
proxy for the whole internet.

Checked once, on the pasted id — files *inside* an approved folder are not
re-checked. If it sits in the trainer's folder, the trainer vouched for it, and
that correctly covers files other people placed there.

An owner matches on ANY populated identity field, because Google may redact
`emailAddress` for API-key requests and leave only `permissionId`. `displayName`
is never accepted — it is user-settable, so anyone could claim it.
"""
from __future__ import annotations

import os

from railway.features.drive_relay.drive_client import DriveFile


def _split_env(name: str, lowercase: bool) -> frozenset[str]:
    raw = os.environ.get(name, "")
    values = (part.strip() for part in raw.split(","))
    return frozenset(v.lower() if lowercase else v for v in values if v)


def configured_identity() -> tuple[frozenset[str], frozenset[str]]:
    """(allowed owner emails, allowed owner permission ids) from the environment."""
    return (
        _split_env("DRIVE_OWNER_EMAILS", lowercase=True),
        _split_env("DRIVE_OWNER_PERMISSION_IDS", lowercase=False),
    )


def is_owned_by_host(
    file: DriveFile,
    *,
    emails: frozenset[str],
    permission_ids: frozenset[str],
) -> bool:
    """True when some owner of ``file`` is a configured trainer identity.

    Fails closed: no configuration, or no owner information from Drive, means no.
    """
    for owner in file.owners:
        if owner.email and owner.email.lower() in emails:
            return True
        if owner.permission_id and owner.permission_id in permission_ids:
            return True
    return False
