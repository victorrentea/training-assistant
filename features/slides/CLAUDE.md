# Slides

## Purpose
Manages PDF slide decks shown to participants. Slides come from four sources (uploaded, local `server_materials/slides/`, daemon-posted state, and a catalog file); they are merged and served via a unified endpoint. The daemon converts PPTX files and uploads resulting PDFs via WebSocket.

## Endpoints
- `POST /api/slides/current` — daemon sets the currently-displayed slide (`url`, `slug`, `source_file`, `current_page`)
- `DELETE /api/slides/current` — daemon clears the current slide
- `GET /api/slides` — public; returns merged + ordered list of all available slide decks
- `GET /api/slides/file/{slug}` — public; serves a PDF file; supports ETag/If-Modified-Since caching
- `GET /api/slides/catalog-map` — returns catalog file path + resolved PPTX→PDF entries
- `POST /api/slides/upload` — daemon uploads a converted PDF file
- `GET /api/slides/drive-status` — returns Drive sync status for on-demand slide fetching

## State Fields
Fields in `AppState` owned by this feature:
- `slides: list[dict]` — daemon-reported slides `[{name, slug, url, updated_at, etag, ...}]`
- `slides_current: dict | None` — currently displayed slide `{url, slug, source_file, presentation_name, current_page, updated_at}`
- `daemon_ws: WebSocket | None` — active daemon WebSocket connection (for on-demand slide upload requests)

## Design Decisions
- Four slide sources, merged in priority order: uploaded > local_materials > state (daemon-posted) > catalog.
- Catalog file (`daemon/materials_slides_catalog.json`) maps course names to PPTX paths; determines ordering on participant page.
- External slide URLs are rewritten to `/api/slides/file/{slug}` to enforce inline PDF rendering in browsers.
- On-demand fetching: if a slug isn't found locally and the daemon WS is connected, the server waits for the daemon to upload the file before responding.
- Slide files are served with `Cache-Control: public, max-age=86400` + ETag + Last-Modified for client-side caching.
- `_is_displayable_slide_name()` filters out internal/hidden file names (e.g. files starting with `.`).
