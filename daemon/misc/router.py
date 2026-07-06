"""Daemon misc router — participant + host endpoints for paste, notes, summary, slides cache."""
import asyncio
import base64
import logging
import urllib.request
from collections import defaultdict
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from daemon import files_md as _files_md
from daemon.email_notify import notify as email_notify
from daemon.misc.content_files import (
    get_active_session_folder,
    read_notes_content,
    read_summary_payload,
)
from daemon.misc.state import misc_state
from daemon.participant.state import participant_state
from daemon.slides.models import Deck, SlidesHistoryResponse, SlidesLogEntry
from daemon.summary.highlight import REJECTED, HighlightAnchor, apply_highlight_to_file
from daemon.summary.loop import AI_SUMMARY_FILE, get_ai_summary_mtime
from daemon.ws_messages import PasteReceivedMsg, SummaryUpdatedMsg
from daemon.ws_publish import broadcast, notify_host

logger = logging.getLogger(__name__)


# ── Pydantic models ──
class PasteRequest(BaseModel):
    text: str

class FeedbackRequest(BaseModel):
    text: str
    participant_name: str | None = None

class NotesResponse(BaseModel):
    notes_content: Optional[str] = None

class SummaryPoint(BaseModel):
    text: str
    source: str

class SummaryResponse(BaseModel):
    points: list[SummaryPoint] = []
    raw_markdown: Optional[str] = None
    updated_at: Optional[str] = None

class HighlightRequest(BaseModel):
    """A host-selected passage to wrap in <mark>, as a race-safe text-quote anchor."""
    exact: str
    prefix: str = ""
    suffix: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    base_rev: Optional[str] = None

class HighlightResponse(BaseModel):
    status: str  # applied | relocated | rejected
    updated_at: Optional[str] = None
    reason: str = ""

class AgendaResponse(BaseModel):
    data: str  # base64-encoded .docx content
    filename: str

class DecksResponse(BaseModel):
    decks: dict[str, Deck] = {}

class PasteEntry(BaseModel):
    id: str
    text: str

class PastsResponse(BaseModel):
    pastes: dict[str, list[PasteEntry]] = {}

class UploadSeenRequest(BaseModel):
    uuid: str
    file_id: str


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant", tags=["misc"])


@participant_router.post("/paste", status_code=204)
async def paste_text(request: Request, body: PasteRequest):
    """Participant pastes text to be seen by host."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    text = body.text
    if not text or len(text) > 102400:  # 100KB limit
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    entry = misc_state.add_paste(pid, text)
    if entry is None:
        return JSONResponse({"error": "Paste limit reached (max 10)"}, status_code=409)

    # Send only to host (not broadcast to all participants)
    await notify_host(PasteReceivedMsg(uuid=pid, **entry))

    return Response(status_code=204)


@participant_router.post("/misc/feedback", status_code=204)
async def participant_feedback(request: Request, body: FeedbackRequest):
    """Participant feedback submitted from floating feedback modal."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    text = (body.text or "").strip()
    if not text or len(text) > 5000:
        return JSONResponse({"error": "Invalid feedback text"}, status_code=400)

    session_name = _get_session_name_for_feedback() or "unknown"
    participant_name = (body.participant_name or "").strip()
    if participant_name:
        participant_name = participant_name[:64]
    else:
        participant_name = participant_state.participant_names.get(pid, pid)
    email_notify(
        f"Participant Feedback ({session_name})",
        f"Participant: {participant_name}\nSession: {session_name}\n\n{text}",
    )
    logger.info("Feedback received from participant %s", pid)
    return Response(status_code=204)


def _get_session_name_for_feedback() -> str | None:
    """Return the active session name."""
    from daemon.session import state as session_shared_state
    return session_shared_state.get_active_session_name()


@participant_router.get("/notes", response_model=NotesResponse)
async def get_notes():
    """Get session notes content."""
    return NotesResponse(notes_content=read_notes_content())


@participant_router.get("/summary", response_model=SummaryResponse)
async def get_summary():
    """Get summary points and raw markdown."""
    summary = read_summary_payload()
    return SummaryResponse(
        points=summary["points"],
        raw_markdown=summary["raw_markdown"],
        updated_at=summary["updated_at"],
    )


class FilesMdResponse(BaseModel):
    raw_markdown: str
    updated_at: str | None


@participant_router.get("/files-md", response_model=FilesMdResponse)
async def get_files_md():
    """Return the per-session files.md content with HTML comments stripped."""
    from datetime import datetime, timezone

    from daemon.misc.content_files import get_active_session_folder

    folder = get_active_session_folder()
    if folder is None:
        return FilesMdResponse(raw_markdown=_files_md.EMPTY_STATE, updated_at=None)
    _files_md.migrate_session_if_needed(folder)
    # Trigger a load so any historical noise entries get pruned + auto-saved.
    _files_md._load_doc(folder)
    target = folder / "files.md"
    if not target.exists():
        return FilesMdResponse(raw_markdown=_files_md.EMPTY_STATE, updated_at=None)
    raw = target.read_text(encoding="utf-8")
    sanitized = _files_md.sanitize_for_wire(raw)
    iso = datetime.fromtimestamp(target.stat().st_mtime_ns / 1e9, tz=timezone.utc).isoformat()
    return FilesMdResponse(raw_markdown=sanitized, updated_at=iso)


@participant_router.get("/slides/decks", response_model=DecksResponse)
async def get_slides_decks():
    """Get slides cache status for all known decks; called on initial page load (decks_updated WS carries full data and replaces polling)."""
    from daemon.slides.router import _slides_updated_with_titles
    return DecksResponse.model_validate({"decks": _slides_updated_with_titles()})


@participant_router.get("/slides/history", response_model=SlidesHistoryResponse)
async def get_slides_history():
    """Return accumulated slide viewing history for the current session."""
    entries = [
        SlidesLogEntry(slug=sv["slug"], slide=sv["page"], seconds_spent=sv["seconds"], last_seen_at=sv.get("last_seen_at"))
        for sv in misc_state.slides_viewed
    ]
    return SlidesHistoryResponse(slides_log=entries)


@participant_router.get("/agenda", response_model=AgendaResponse)
async def get_agenda():
    """Serve the agenda .docx as base64-encoded JSON (survives WS proxy)."""
    path = misc_state.agenda_docx_path
    if not path or not path.exists():
        return JSONResponse({"error": "No agenda available"}, status_code=404)
    try:
        raw = path.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        return AgendaResponse(data=encoded, filename=path.name)
    except OSError:
        return JSONResponse({"error": "Failed to read agenda file"}, status_code=500)


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host", tags=["misc"])


@host_router.get("/pastes", response_model=PastsResponse)
async def get_pastes():
    """Return all pending paste entries grouped by participant uuid."""
    return PastsResponse.model_validate({"pastes": misc_state.paste_texts})


@host_router.get("/notes", response_model=NotesResponse)
async def get_host_notes():
    """Return current session notes content."""
    return NotesResponse(notes_content=read_notes_content())


@host_router.get("/summary", response_model=SummaryResponse)
async def get_host_summary():
    """Return summary points, raw markdown, and updated_at timestamp."""
    summary = read_summary_payload()
    return SummaryResponse(
        points=summary["points"],
        raw_markdown=summary["raw_markdown"],
        updated_at=summary["updated_at"],
    )


# Serializes concurrent highlight applies within the daemon; cross-process races
# (an AI editing ai-summary.md) are handled by the resolver's re-read + relocate.
_highlight_lock = asyncio.Lock()


@host_router.post("/summary/highlight", response_model=HighlightResponse)
async def highlight_summary(body: HighlightRequest):
    """Wrap a host-selected passage of ai-summary.md in <mark>, deterministically.

    Race-safe against a concurrent AI editing the same file: the anchor is
    resolved against the current file at write time, or the request is rejected
    (409) if the passage moved/changed — so content is never scrambled.
    """
    folder = get_active_session_folder()
    if folder is None:
        return JSONResponse(status_code=404, content={"detail": "no active session"})
    anchor = HighlightAnchor(
        exact=body.exact, prefix=body.prefix, suffix=body.suffix,
        start=body.start, end=body.end, base_rev=body.base_rev,
    )
    async with _highlight_lock:
        result = await asyncio.to_thread(
            apply_highlight_to_file, folder / AI_SUMMARY_FILE, anchor
        )
    if result.status == REJECTED:
        return JSONResponse(
            status_code=409, content={"status": REJECTED, "reason": result.reason},
        )
    updated_at = get_ai_summary_mtime(folder)
    broadcast(SummaryUpdatedMsg(updated_at=updated_at))  # participants refresh the summary
    return HighlightResponse(status=result.status, updated_at=updated_at, reason=result.reason)


# Local-only alias for the highlight above, reachable at a simple URL with NO
# {session_id} in the path. A highlight is a host-machine-only action and the
# daemon already serves a single active session, so it needs no session scoping —
# the handler resolves the target file from the active session on its own. The
# host summary page (served from Railway) calls this directly on 127.0.0.1, never
# via the Railway gateway.
local_router = APIRouter(tags=["misc"])


@local_router.post("/summary/highlight", response_model=HighlightResponse)
async def highlight_summary_local(body: HighlightRequest):
    return await highlight_summary(body)


@host_router.post("/uploads/seen", status_code=204)
async def mark_uploaded_file_seen(body: UploadSeenRequest):
    """Mark an uploaded-file indicator as seen by host in daemon session state."""
    target_uuid = (body.uuid or "").strip()
    file_id = str(body.file_id or "").strip()
    if not target_uuid or not file_id:
        return JSONResponse({"error": "uuid and file_id are required"}, status_code=400)
    if not misc_state.mark_uploaded_file_seen(target_uuid, file_id):
        return JSONResponse({"error": "Upload indicator not found"}, status_code=404)
    return Response(status_code=204)


def _fetch_pdf_bytes_from_railway(session_id: str, slug: str) -> bytes:
    """Fetch a cached PDF from Railway. The download endpoint is public (no auth needed)."""
    from daemon.slides.router import _railway_base_url, _ssl_context
    url = f"{_railway_base_url()}/{session_id}/api/slides/download/{slug}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60.0, context=_ssl_context()) as resp:
        return resp.read()


@host_router.get("/slides-compilation")
async def get_slides_compilation(session_id: str):
    """Compile all viewed slide pages into one PDF and return as a download.

    Long-running: may trigger Railway to download PDFs from Google Drive first.
    Progress is logged to the daemon log.
    """
    from daemon import log
    from daemon.slides.router import download_on_railway

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        log.error("slides-compile", "pypdf not installed — add to [daemon] extras in pyproject.toml")
        return JSONResponse({"error": "pypdf not available"}, status_code=500)

    # 1. Group slides_viewed by slug, preserving encounter order
    pages_by_slug: dict[str, set[int]] = defaultdict(set)
    slug_order: list[str] = []
    for sv in misc_state.slides_viewed:
        slug = sv.get("slug", "")
        if not slug:
            continue
        if slug not in pages_by_slug:
            slug_order.append(slug)
        page = sv.get("page", 0)
        if page > 0:
            pages_by_slug[slug].add(page)

    if not slug_order:
        return Response(status_code=204)

    # 2. Resolve slugs to catalog entries
    needed: list[dict] = []  # each: {slug, drive_export_url, pages}
    for slug in slug_order:
        catalog_entry = misc_state.slides_catalog.get(slug)
        if not catalog_entry:
            log.error("slides-compile", f"No catalog entry for slug={slug!r} — skipping")
            continue
        pages = pages_by_slug[slug]
        if pages:
            needed.append({"slug": slug, "drive_export_url": catalog_entry.get("drive_export_url", ""), "pages": pages})

    if not needed:
        return Response(status_code=204)

    # 4. Parallel prefetch of PDFs not yet cached on Railway
    total = len(needed)
    uncached = [
        d for d in needed
        if misc_state.slides_updated.get(d["slug"], {}).get("status") != "cached"
    ]
    done_count = total - len(uncached)
    log.info("slides-compile", f"Starting: {total} decks, {len(uncached)} need GDrive download")

    if uncached:
        counter_lock = asyncio.Lock()

        async def _prefetch(deck: dict) -> None:
            nonlocal done_count
            try:
                await asyncio.to_thread(download_on_railway, deck["slug"], deck["drive_export_url"])
            except Exception as exc:
                log.error("slides-compile", f"GDrive download failed for {deck['slug']!r}: {exc}")
            async with counter_lock:
                done_count += 1
                pct = int(done_count * 100 / total)
                log.info("slides-compile", f"Prefetch {done_count}/{total} ({pct}%)")

        await asyncio.gather(*[_prefetch(d) for d in uncached])

    # 5. Fetch PDFs from Railway and extract viewed pages
    writer = PdfWriter()
    total_pages = 0

    for deck in needed:
        slug = deck["slug"]
        pages = sorted(deck["pages"])
        try:
            pdf_bytes = await asyncio.to_thread(_fetch_pdf_bytes_from_railway, session_id, slug)
        except Exception as exc:
            log.error("slides-compile", f"Failed to fetch PDF for {deck['slug']!r}: {exc}")
            continue
        reader = PdfReader(BytesIO(pdf_bytes))
        n = len(reader.pages)
        for p in pages:
            if 1 <= p <= n:
                writer.add_page(reader.pages[p - 1])
                total_pages += 1

    log.info("slides-compile", f"Done — {total_pages} pages compiled from {len(needed)} decks")

    import re

    from daemon.session import state as session_shared_state
    raw_name = session_shared_state.get_active_session_name() or ""
    safe_name = re.sub(r"[^\w\s\-]", "", raw_name).strip().replace(" ", "-")
    filename = f"slides-compilation-{safe_name}.pdf" if safe_name else "slides-compilation.pdf"

    buf = BytesIO()
    writer.write(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
