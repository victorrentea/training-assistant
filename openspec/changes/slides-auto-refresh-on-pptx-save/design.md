## Context

The system has two daemon processes: the **main daemon** (FastAPI, handles WS to Railway, quiz, transcripts) and the **slides upload daemon** (`python3 -m daemon.slides.upload`, polls PPTX mtimes and downloads from GDrive). They share a state file (`pptx_daemon_state.json`) on disk but run in separate processes with separate memory.

When a PPTX is saved, the slides upload daemon correctly detects the mtime change, waits for GDrive to mirror the new PDF (fingerprint polling), and downloads it locally. However, it never tells Railway to invalidate its cached copy (`/tmp/slides-cache/{slug}.pdf`). Railway continues serving the stale PDF to participants indefinitely. Participants are never notified to reload.

The main daemon holds the WS connection to Railway. Only it can send `download_pdf` messages to Railway. The slides upload daemon has no WS access.

## Goals / Non-Goals

**Goals:**
- Invalidate Railway's cached PDF automatically when PPTX is saved and GDrive has the new version
- Notify all connected participants that the PDF was updated
- Auto-reload the active slide on participant pages when it is the updated deck

**Non-Goals:**
- Changing how GDrive polling works (fingerprint detection is already correct)
- Supporting local-conversion flow (removed, only `google_drive_pull` remains)
- Pushing the PDF directly from daemon to Railway (Railway fetches from GDrive itself)

## Decisions

### 1. Slides upload daemon notifies main daemon via REST
After `process_one_file()` succeeds, the slides upload daemon POSTs to `POST /api/slides/invalidate/{slug}` on the main daemon (at `config.server_url`, which defaults to `http://localhost:8081` for local daemon-to-daemon calls). This endpoint requires host auth, marks the slug as `stale` in `misc_state.slides_cache_status`, and sends a `download_pdf` WS message to Railway.

This is consistent with the existing architecture where daemon-to-daemon REST is used (e.g. `push_slides_list`, `push_current_slides` already POST to the server).

### 2. Railway re-download uses existing `download_pdf` → `pdf_download_complete` flow
No new WS protocol needed. Railway already handles `download_pdf` and sends `pdf_download_complete` back. The existing `handle_pdf_download_complete` on the daemon side already broadcasts `slides_cache_status` when it receives this.

### 3. Participant auto-reloads currently displayed PDF
When participant JS receives `slides_cache_status` and the freshly-cached slug matches the currently rendered slide deck (`_currentSlug`), it calls `_reloadCurrentSlide()` which re-requests the PDF iframe src. No extra WS message type needed.

### 4. New `slides-invalidate-on-save` spec tracks the new behavior
A new spec file covers the invalidation + notification requirements. The modified `slides` spec delta covers the participant auto-reload behavior.

## Risks / Trade-offs

- **Race condition**: If slides upload daemon calls `/invalidate` while Railway is already downloading (from a participant `/check`), the second `download_pdf` will coalesce in the daemon's `_pending_checks` dict — no duplicate download.
- **Main daemon not running**: If the main daemon is not running when the slides upload daemon calls `/invalidate`, the call silently fails (logged as warning). This is acceptable — the existing behavior was to do nothing.
- **`config.server_url` in slides upload daemon**: Points to Railway in prod, localhost in dev. The invalidate call should go to the **main daemon** (port 8081), not Railway. A new `DAEMON_LOCAL_URL` config key (defaulting to `http://localhost:8081`) should be used for daemon-to-daemon calls.
