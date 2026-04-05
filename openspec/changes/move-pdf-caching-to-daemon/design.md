## Context

Railway currently owns the full PDF caching pipeline autonomously: it receives a `slides_catalog` WS message from the daemon, seeds catalog state from a static JSON file at startup, polls GDrive fingerprints, downloads PDFs into `/tmp/slides-cache/`, tracks cache status per slug, and broadcasts `slides_cache_status` to participants. This is ~886 lines across `cache.py` and `router.py`.

The daemon already sends `slides_catalog` and `slide_invalidated` WS messages to Railway and handles PPTX file watching in `daemon/slides/`. The daemon is the architectural source of truth. Railway is a proxy + file server.

Participant REST calls (including `GET /{sid}/api/slides`) are **transparently proxied by Railway to the daemon** — Railway does not handle them itself. Railway cannot initiate REST calls to daemon (daemon is on localhost; Railway can only communicate to daemon via WS messages on the existing daemon WS connection).

## Goals / Non-Goals

**Goals:**
- Daemon becomes the decision-maker for all PDF caching: fingerprint polling, staleness detection, instructing Railway to download
- New `GET /{sid}/api/slides/check/{slug}` endpoint (proxied to daemon): participant must call this before downloading; daemon blocks the response until the PDF is confirmed fresh (or times out at 30s → 503)
- `GET /{sid}/api/slides` proxied to daemon (daemon returns slide index + cache status as source of truth)
- Railway retains the actual GDrive HTTP pull machinery and file storage — but only executes on daemon's instruction
- Railway notifies daemon via WS when a download completes; daemon broadcasts `slides_cache_status` to all participants — even those who already got a 503 can clear their "Retry" state and show the green cached indicator
- **Lazy downloads only**: daemon SHALL NOT pre-emptively download PDFs on reconnect or catalog push. Downloads are triggered exclusively by participant `/check` requests. This avoids unnecessary GDrive→Railway traffic for slides no participant is actively viewing.

**Non-Goals:**
- Moving PDF files off Railway — they stay, served directly to participants
- Changing how PDFs are generated (Google Drive generates them from PPTX)
- Changing the participant or host frontend beyond the `/check` call and handling the `slides_cache_status` broadcast to clear retry state
- Removing the daemon WS connection
- Proactive/background pre-warming of the PDF cache

## Decisions

### 1. Railway keeps the GDrive HTTP pull machinery; daemon only coordinates

**Why**: Railway already has working download code (SSL context, fingerprint probing, download+verify, per-slug locking) in `cache.py`. Moving the actual HTTP calls to daemon and re-uploading would add a large binary transfer through the trainer's Mac for every PDF. Railway is co-located with its `/tmp/slides-cache/` storage. Daemon just says "download this slug" via a WS message.

**Alternatives considered**:
- Daemon downloads and uploads to Railway: rejected — large binary traffic through the trainer's Mac; Railway already has the machinery.
- Keep Railway fully autonomous: rejected — Railway can't make the freshness/staleness judgment without GDrive fingerprint awareness, which the daemon owns.

### 2. New `download_pdf` WS message daemon→Railway; `pdf_download_complete` WS message Railway→daemon

**Why**: The only Railway→daemon channel available is a WS message on the existing daemon WS connection. Daemon instructs Railway with `{type: "download_pdf", slug, drive_export_url}`; Railway responds with `{type: "pdf_download_complete", slug, status: "ok"|"error"}` once done.

### 3. `/check` is a blocking long-poll on daemon (up to 30s), not a polling loop from participant

**Why**: Simpler participant JS — one call, either succeeds or gets 503. No polling. Daemon holds the request open while it waits for the `pdf_download_complete` WS notification from Railway.

After a 503 timeout, the participant shows a "Retry" button. When Railway eventually finishes the download (daemon still receives `pdf_download_complete` even after the timeout), daemon broadcasts `slides_cache_status` to all participants — participant JS clears the "Retry"/error state and replaces it with the green cached indicator automatically.

**Alternatives considered**:
- Participant polls a status endpoint: more JS complexity, chattier protocol.
- Webhook/SSE: overkill for a 30s gate.

### 4. Lazy-only downloads — no proactive pre-warming

**Why**: Avoids pulling potentially large PDFs from GDrive to Railway for slides no participant ever opens. On reconnect or catalog push, daemon updates its catalog state but issues no `download_pdf` messages. Downloads happen only when a participant `/check` triggers them.

**Alternatives considered**:
- Pre-warm all slides on daemon reconnect: wastes bandwidth when participants aren't viewing slides yet; unnecessary for a live workshop where the host navigates slide-by-slide.

### 4. `GET /{sid}/api/slides` proxied to daemon

**Why**: Daemon is the source of truth for the slide catalog and cache status. Railway proxying it is consistent with how all other `/{sid}/api/...` participant endpoints work. Eliminates the `_build_catalog_slides_index` / `_merge_slide_sources` complexity from Railway.

### 5. Remove `seed_catalog_from_file()` and autonomous Railway download triggering

**Why**: With daemon as coordinator, Railway should never act on catalog data before daemon instructs it. The seed workaround existed for daemon-offline cold starts — now if daemon is offline, participants simply see "unavailable" on slides, which is acceptable.

### 6. Remove per-slug asyncio locks, semaphore, download events, and fingerprint state from Railway's AppState

**Why**: These supported Railway's autonomous download orchestration. With daemon coordinating, Railway only needs to execute a single download per daemon instruction. Per-slug locking can be simplified to just tracking in-flight downloads to deduplicate concurrent daemon requests for the same slug.

## Risks / Trade-offs

- **Cold start with daemon offline**: Participants see no GDrive slides until daemon connects. Mitigation: daemon connects quickly; this is already the behaviour when daemon is freshly started.
- **30s timeout on `/check`**: Large PDFs (>30s download) result in 503 to participant. Mitigation: Railway should stream download progress status back; daemon can extend timeout or participant retries.
- **Daemon restart mid-check**: A pending `/check` request is lost if daemon restarts. Participant gets a connection error → naturally retries. Acceptable.
- **Railway restart loses cached files**: `/tmp/slides-cache/` is ephemeral on Railway. Next `/check` from any participant will trigger a fresh download. No proactive reconciliation on reconnect (lazy-only design).

## Migration Plan

1. Add `GET /api/slides/cache-status` on Railway — returns current `slides_cache_status` dict; daemon calls this on reconnect to know what's already cached.
2. Add `download_pdf` WS message handler on Railway — triggers existing `_do_download` machinery; sends `pdf_download_complete` WS back to daemon when done.
3. Add `pdf_download_complete` WS message handler on Railway→daemon path — daemon receives it to unblock pending `/check` responses.
4. Add `GET /{sid}/api/slides/check/{slug}` on daemon — holds response open, instructs Railway to download if needed, resolves on `pdf_download_complete` or 503 after 30s.
5. Add `GET /{sid}/api/slides` on daemon — returns merged slide index + cache status.
6. Update Railway `GET /{sid}/api/slides` to proxy to daemon (like other participant endpoints).
7. Port fingerprint polling logic from `cache.py` into `daemon/slides/convert.py`; connect to existing `slide_invalidated` handler.
8. On `pdf_download_complete`, daemon updates its cache-status dict and broadcasts `slides_cache_status` to all participants (clears "Retry"/error state in participant UI).
9. Remove `seed_catalog_from_file()` from Railway startup.
10. Remove autonomous download triggering from Railway's `slide_invalidated` handler (Railway now only acts on `download_pdf` WS messages).
11. Remove dead AppState fields: `slides_gdrive_locks`, `slides_download_events`, `slides_fingerprints`, `slides_download_semaphore`.
12. Remove `_build_catalog_slides_index`, `_build_local_slides_index`, `_build_uploaded_slides_index`, `_merge_slide_sources` from `router.py`.

**Rollback**: daemon changes are additive; Railway changes can be reverted independently.

## Open Questions

- Should Railway report per-slug download progress bytes (for participant progress bars) or only terminal states (`downloading` → `cached`/`error`)? Currently the `slides_cache_status` broadcast includes an intermediate `downloading` state.
