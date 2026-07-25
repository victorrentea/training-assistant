"""Host-only endpoint serving the live `attendees.md` attendance sheet.

Mirrors the other host routers (e.g. `daemon/leaderboard/router.py`): a small
`APIRouter` mounted under `/api/{session_id}/host` in `daemon/host_server.py`.

The document is rendered fresh on read from the live roster
(:func:`daemon.attendees_md.build_attendees_md`), so the host always downloads
the current attendance independent of the write-side regeneration that keeps the
on-disk file live. When no session is active it returns the "no attendees yet"
placeholder with a 200 (never a server error), per the host-attendees-pdf spec.
"""
from fastapi import APIRouter, Response

from daemon.attendees_md import build_attendees_md

router = APIRouter(prefix="/api/{session_id}/host", tags=["attendees"])


@router.get("/attendees.md")
async def get_attendees_md() -> Response:
    """Return the current `attendees.md` for the active session as Markdown text."""
    text = build_attendees_md()
    return Response(content=text, media_type="text/markdown; charset=utf-8")
