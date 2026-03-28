# Server-Side PDF Caching from Google Drive

## Problem

PDFs are currently served to participants through the daemon on the trainer's Mac: the daemon watches local PPTX files, converts via Google Drive export, and uploads PDFs to the FastAPI backend. This creates a heavy dependency on the daemon for slide delivery and puts conversion/polling logic in the wrong place.

## Goal

Move PDF caching and Google Drive interaction to the FastAPI backend on Railway. The daemon becomes a thin file watcher that sends two messages: "here's the catalog" and "slide X changed." The backend handles everything else: downloading, fingerprint polling, caching, dedup, and status reporting.

## Architecture

### Daemon (trainer's Mac) — thin file watcher

**On WS connect**, sends the full catalog:
```json
{
  "type": "slides_catalog",
  "entries": [
    {"slug": "clean-code", "title": "Clean Code", "drive_export_url": "https://docs.google.com/presentation/d/.../export/pdf"},
    ...
  ]
}
```

This **replaces** the existing `slides_meta` message. The backend does NOT read the catalog JSON file — it only learns about slides from the daemon. When the daemon is offline, the backend cannot download new slides (but serves any already-cached PDFs from disk).

**On PPTX mtime change**, sends:
```json
{"type": "slide_invalidated", "slug": "clean-code"}
```

**Receives log messages** from BE for console output:
```json
{"type": "slide_log", "slug": "clean-code", "event": "download_started", "detail": "size=2.1MB"}
```

The daemon no longer converts PPTX, polls GDrive fingerprints, or uploads PDFs.

### Backend (Railway FastAPI) — PDF authority

**Cache directory**: `/tmp/slides-cache/{slug}.pdf` (ephemeral, lost on redeploy — acceptable).

**Catalog**: stored in `state.slides_catalog` (dict of slug -> entry), populated when daemon connects. This is the sole source of `drive_export_url` data. When daemon disconnects, catalog is retained in memory (not cleared) so cached PDFs can still be served.

**Per-slide state machine**:
```
not_cached ──(participant requests)──> downloading ──(success)──> cached
                    │                       │                        │
                    │                  (failure)              (slide_invalidated)
                    │                       ↓                        ↓
                    │                 download_failed              stale
                    │                       │                        │
                    │            (participant re-requests)  (3s delay, then HEAD poll)
                    │                       ↓                        ↓
                    └───────────────> downloading              polling_drive
                                                              │         │
                                                   (fp changed)  (timeout ~60s)
                                                              ↓         ↓
                                                        downloading  poll_timeout ──(slide_invalidated)──> stale
                                                              ↓       (serve old PDF)
                                                            cached
```

**Any state** can receive `slide_invalidated` → transitions to `stale` (if a PDF exists on disk) or stays `not_cached` (if no PDF yet).

**`poll_timeout`** is not terminal: a new `slide_invalidated` from the daemon restarts the poll cycle via `stale`.

**`download_failed`** transitions: the slide goes to `download_failed` state. Old cached PDF (if any) is still served. A new participant request or `slide_invalidated` retriggers the download.

**Status enum values** (pushed to host UI via WS):
- `not_cached` — never downloaded, no participant requested it yet
- `downloading` — download from GDrive in progress
- `cached` — PDF on disk, ready to serve
- `stale` — daemon reported PPTX change, still serving old PDF while re-syncing
- `polling_drive` — probing GDrive every 3s waiting for fingerprint change
- `poll_timeout` — GDrive fingerprint didn't change within 60s; still serving last cached version
- `download_failed` — download attempt failed; retryable on next request or invalidation

### Per-slug GDrive lock (critical constraint)

**At most ONE in-flight HTTP request to Google Drive per slug at any time.** This is the single most important concurrency rule. No matter what triggers a GDrive call — participant request, fingerprint poll HEAD, invalidation re-download — they all go through one `asyncio.Lock` per slug (`state.slides_gdrive_locks[slug]`). Anyone else wanting GDrive access for that slug awaits the lock.

This prevents: 20 participants requesting the same slide → 20 parallel GDrive downloads. Instead: first request acquires the lock and downloads; the other 19 await an `asyncio.Event` that fires when the download completes.

**Implementation**:
- `state.slides_gdrive_locks`: `dict[str, asyncio.Lock]` — one lock per slug, lazily created
- `state.slides_download_events`: `dict[str, asyncio.Event]` — signals waiters when a download completes
- All GDrive HTTP calls (HEAD probes, GET downloads) acquire the slug's lock first
- Participant requests that find a download already in progress skip the lock entirely and just `await` the event (timeout 60s)

**Cross-slug concurrency limit**: at most 3 simultaneous GDrive downloads across all slugs (global `asyncio.Semaphore`). This prevents thundering herd after a redeploy when many participants request different slides at once. Additional downloads queue behind the semaphore.

### GDrive fingerprint polling (on invalidation)

**HEAD vs GET fallback**: Google Drive export URLs sometimes return 405 on HEAD, or return no useful headers (no ETag/Last-Modified/Content-Length). The existing daemon code falls back to a full GET + SHA256 hash in that case. The backend must implement the same fallback. To minimize bandwidth:
1. Try HEAD first (cheap, ~0 bytes)
2. If HEAD returns useful headers → use them as fingerprint
3. If HEAD returns 405 or empty headers → fall back to GET, but only for the first probe to establish a baseline fingerprint, then use HEAD for subsequent checks (Content-Length alone may change)
4. If HEAD consistently fails → fall back to GET every poll tick (worst case: ~20 full downloads in 60s for one slide — acceptable as a rare edge case)

**Duplicate invalidation handling**: if `slide_invalidated` arrives while already in `polling_drive` for the same slug, ignore it (the poll is already running). If it arrives in `downloading` state, ignore it (will re-check after download completes).

When BE receives `slide_invalidated`:
1. If already `polling_drive` or `downloading` for this slug → ignore
2. Mark slide as `stale`
3. Store current fingerprint (from last download's saved fingerprint)
4. Wait 3 seconds (allow GDrive to start syncing)
5. Every 3 seconds, probe `drive_export_url` (HEAD with GET fallback)
6. Compare fingerprint against stored value
7. If changed → transition to `downloading`, fetch full PDF, transition to `cached`
8. If 60s elapsed with no change → transition to `poll_timeout`, log warning
9. Push status updates to host UI at each transition
10. Send `slide_log` messages to daemon at each transition

### Participant request flow

```
GET /api/slides/file/{slug}
  ├─ PDF exists in /tmp/slides-cache/{slug}.pdf
  │   └─ Serve immediately (with ETag/Last-Modified headers)
  ├─ No PDF, catalog has drive_export_url
  │   ├─ Download already in progress? → await existing event (timeout 60s)
  │   └─ No download in progress? → start download (through semaphore), await event
  │   └─ Serve PDF after download completes (or 504 on timeout/failure)
  └─ No PDF, no catalog entry → 404
```

### BE → Daemon log messages

All sent as `{"type": "slide_log", "slug": "...", "event": "...", "detail": "..."}`:

| event | when | detail example |
|-------|------|----------------|
| `catalog_received` | daemon pushes catalog | `entries=15` |
| `download_started` | PDF download begins | `url=https://...` |
| `download_complete` | PDF saved to cache | `size=2.1MB elapsed=3.2s` |
| `download_failed` | download error | `HTTP 403: Forbidden` |
| `invalidated` | daemon reports change | — |
| `poll_started` | fingerprint polling begins | `fingerprint=hdr:etag\|...\|1234` |
| `poll_check` | each HEAD poll tick | `attempt=3 fingerprint=hdr:...` |
| `poll_fingerprint_changed` | new fingerprint detected | `old=hdr:... new=hdr:...` |
| `poll_timeout` | 60s elapsed, no change | `attempts=20` |

### Host UI tooltip (📜 popover)

Each slide line shows a colored status marker with brief label:

```
🟢 cached     Clean Code           2.1 MB  3m ago
🔄 syncing    Design Patterns
🟡 stale      Architecture
🔴 not cached Code Smells
⚠  timeout    Spring
❌ failed     Refactoring
```

Status is pushed via the WS broadcast state mechanism (in `slides` state builder). The popover renders from `state.slides_cache_status` which is a dict of `slug -> {status, size_bytes, downloaded_at, title}`.

"syncing" label covers `downloading` and `polling_drive` states (user doesn't need that distinction).

## Files Changed

| File | Change |
|------|--------|
| `features/slides/cache.py` | **New** — download from GDrive, fingerprint probe (HEAD+GET fallback), poll loop, dedup events, download semaphore, status tracking, daemon log push |
| `features/slides/router.py` | Modify — `GET /api/slides/file/{slug}` serves from cache; remove on-demand daemon upload flow (`slides_upload_request`/`slides_upload_result` WS messages and `drive_status.py` logic) |
| `features/slides/drive_status.py` | **Remove** — replaced by `cache.py` |
| `features/slides/state_builder.py` | Modify — include `slides_cache_status` in host WS state; remove `slides_uploads` |
| `features/ws/router.py` | Modify — handle `slides_catalog` (replaces `slides_meta`) and `slide_invalidated`; remove `slides_upload_result` handling |
| `core/state.py` | Modify — add `slides_catalog`, `slides_cache_status`, `slides_download_events`, `slides_fingerprints`, `slides_download_semaphore`; remove `slides_uploads` |
| `daemon/materials/ws_runner.py` | Modify — send `slides_catalog` on connect (replaces `slides_meta`); handle `slide_log` messages (print to console); remove `slides_upload_request` handling and PDF upload logic |
| `daemon/slides/loop.py` | Modify — on PPTX change send `slide_invalidated` via WS instead of converting+uploading |
| `daemon/slides/convert.py` | **Remove or gut** — PPTX→PDF conversion no longer needed on daemon |
| `daemon/slides/upload.py` | **Remove or gut** — PDF upload to backend no longer needed |
| `daemon/slides/drive_sync.py` | **Keep** — `_probe_drive_fingerprint` and `_download_pdf_from_url` logic moves to `features/slides/cache.py`; daemon no longer calls them but code can be referenced |
| `static/host.js` | Modify — render cache status with colored markers + labels in 📜 popover from WS-pushed state |
| `static/host.css` | Modify — style tweaks for status labels if needed |
| `main.py` | Remove — experimental proof-of-concept ping/download code |

## What stays unchanged

- Participant-facing slide list endpoint (`GET /api/slides`) — still merges from multiple sources
- Uploaded slides (`POST /api/slides/upload`) — direct uploads bypass GDrive entirely
- Slides navigation / current slide tracking — unrelated to caching
- Daemon's PPTX file watching logic — stays, just changes what it does on detection

## Out of scope

- Persistent storage across deploys (accepted: ephemeral `/tmp` is fine)
- Eager pre-caching at startup (accepted: lazy on-demand only)
- Slides without `drive_export_url` in catalog (no GDrive source = cannot cache server-side)
- GDrive authentication — export URLs for files shared "anyone with link" work without auth; if a file is private, it won't work from Railway (same limitation as today's daemon approach for non-Drive-synced files)
