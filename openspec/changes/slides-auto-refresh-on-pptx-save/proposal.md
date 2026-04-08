## Why

When a presenter saves a PowerPoint, participants continue seeing the old cached PDF on Railway — the system never invalidates Railway's local PDF cache or notifies participants to reload. The full update pipeline exists in pieces but is never stitched together end-to-end.

## What Changes

- **New**: The local daemon polls Google Drive and detects when the PDF behind a slide slug has changed
- **New**: Once a new Google Drive PDF is detected, the local daemon notifies the Railway proxy (`POST /api/slides/invalidate/{slug}`) to trigger a fresh download from Google Drive
- **New**: Railway, after completing the re-download, broadcasts `slides_cache_status` to all connected participants (existing mechanism, already fires — but was never triggered by PPTX saves)
- **New**: The participant browser, upon receiving `slides_cache_status`, checks if the updated slug matches the currently displayed slide deck; if so, it automatically reloads the PDF without user interaction

## Capabilities

### New Capabilities
- `slides-invalidate-on-save`: Local-daemon-to-Railway-proxy invalidation signal that triggers Railway to re-download the updated PDF from Google Drive and refresh participants automatically

### Modified Capabilities
- `slides`: Participant page now auto-reloads the active slide when `slides_cache_status` signals that the currently displayed slug just became freshly cached

## Impact

- `daemon/slides/upload.py`: Poll Google Drive for PDF changes and call `/api/slides/invalidate/{slug}` on Railway when a new PDF version is detected
- `railway/slides` (or Railway host router): Handle `POST /api/slides/invalidate/{slug}` by marking slug stale and triggering a fresh Google Drive download
- `railway` service wiring: Register and enforce auth for the invalidate endpoint
- `static/participant.js`: On `slides_cache_status`, detect if the freshly cached slug matches the currently rendered slide deck and trigger reload
- `tests/docker/`: New hermetic E2E test verifying full flow: touch PDF → Railway re-downloads → participants auto-reload
