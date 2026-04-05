## Why

Caching decisions (when to download a PDF, fingerprint polling, staleness detection) currently live on Railway, but Railway has no business logic — it should be a dumb proxy and file server. The daemon is the source of truth for all slide state. Moving orchestration to the daemon also enables the `/check` gate: participants request permission from the daemon before downloading, allowing daemon to ensure the PDF is fresh before serving it.

## What Changes

- **New participant flow**: before downloading a PDF, participant calls `GET /{sid}/api/slides/check/{slug}` (proxied to daemon). Daemon responds immediately if fresh, or blocks until Railway has downloaded/refreshed the PDF (up to 30s timeout → 503).
- **Daemon gains**: fingerprint polling decision logic, cache-status tracking per slug, coordinating Railway downloads via WS message `download_pdf`
- **Railway retains**: the actual GDrive HTTP pull machinery (already in `cache.py`), PDF file storage, file serving — but only executes downloads on daemon's instruction, not autonomously
- **Railway loses**: autonomous download triggering, `seed_catalog_from_file()`, per-slug asyncio locks/semaphore/fingerprint state, catalog index building and source merging
- `GET /{sid}/api/slides` proxied to daemon (source of truth for slide index + cache status)
- `GET /{sid}/api/slides/download/{slug}` remains Railway-served (PDF binary on disk)
- **BREAKING**: Railway no longer self-initiates GDrive downloads; daemon drives all download decisions

## Capabilities

### New Capabilities
- `daemon-pdf-cache-manager`: Daemon owns all caching decisions — fingerprint polling, staleness detection, instructing Railway to download via WS, tracking cache status, and gating participant downloads via `/check`

### Modified Capabilities
- (none — no existing specs to delta against)

## Impact

- `railway/features/slides/cache.py`: trimmed — keeps GDrive HTTP pull + disk write, removes autonomous triggering logic
- `railway/features/slides/router.py`: simplified — removes catalog index building, source merging, `seed_catalog_from_file()`; `GET /api/slides` becomes a proxy passthrough to daemon
- `daemon/slides/`: gains fingerprint polling, cache-status dict, `download_pdf` WS coordination, pending `/check` request handling
- New WS message Railway→daemon: `pdf_download_complete {slug}` (Railway notifies daemon when download finishes)
- New WS message daemon→Railway: `download_pdf {slug, drive_export_url}` (daemon instructs Railway to pull)
- New participant endpoint: `GET /{sid}/api/slides/check/{slug}` (proxied to daemon)
- No change to participant or host frontend beyond the new `/check` call before download
