"""Turn a pasted Google Drive URL into a Drive file id.

Pure string work, no I/O. The id charset is deliberately narrow: Task 3
interpolates the id into Drive's ``q=`` query, and rejecting anything outside
``[A-Za-z0-9_-]`` here is what keeps a quote from escaping into that query.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_ID = r"[A-Za-z0-9_-]{10,}"

# Ordered by how often participants paste them.
_PATH_PATTERNS = (
    re.compile(rf"^/drive/folders/({_ID})$"),
    re.compile(rf"^/drive/u/\d+/folders/({_ID})$"),
    re.compile(rf"^/file/d/({_ID})(?:/.*)?$"),
    re.compile(rf"^/(?:document|spreadsheets|presentation)/d/({_ID})(?:/.*)?$"),
)

_ALLOWED_HOSTS = frozenset({"drive.google.com", "docs.google.com"})


class InvalidDriveLink(ValueError):
    """The pasted text is not a Google Drive link we can act on."""


def parse_drive_url(url: str) -> str:
    """Return the Drive file id in ``url``.

    Raises InvalidDriveLink for anything that is not a recognised Drive URL on a
    Google host. We match known shapes rather than scanning for the first
    id-looking substring, so a link that merely *mentions* a Drive id in a query
    parameter is rejected instead of silently trusted.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or parsed.hostname not in _ALLOWED_HOSTS:
        raise InvalidDriveLink(url)

    path = parsed.path.rstrip("/") or "/"
    for pattern in _PATH_PATTERNS:
        match = pattern.match(path)
        if match:
            return match.group(1)

    if path == "/open":
        candidates = parse_qs(parsed.query).get("id", [])
        if candidates and re.fullmatch(_ID, candidates[0]):
            return candidates[0]

    raise InvalidDriveLink(url)
