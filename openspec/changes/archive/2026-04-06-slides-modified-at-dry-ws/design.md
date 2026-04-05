## Context

The slides feature exposes a `GET /{sid}/api/slides` REST endpoint that returns a list of slide entries with embedded cache metadata. Each entry contains `status`, `size_bytes`, `downloaded_at` (when Railway cached the PDF), and `updated_at` (mapped from `last_exported_mtime` — when the daemon last exported the PPTX to PDF).

Currently:
- `slides_cache_status` WS message carries a full `slides[]` array, duplicating the REST shape
- Participant and host JS update their local slides state directly from the WS payload, bypassing REST
- There is no field exposing when the source PPTX file was last modified on disk (the daemon already reads `pptx.stat().st_mtime` to detect changes but does not store or expose it)
- The participant UI's `_buildSlideItem()` renders the timestamp from `slide.updated_at` — which is `last_exported_mtime`, not source file mtime

## Goals / Non-Goals

**Goals:**
- Add `modified_at` = PPTX `st_mtime` to the `slides[]` REST response so participants see when the source file was last changed on the trainer's machine
- Render `modified_at` on each topic line in the participant slides dock (replacing the existing `updated_at`-based display)
- Make `slides_cache_status` a trigger-only WS event (no payload) so participant and host UIs always call REST to get fresh data (single source of truth)

**Non-Goals:**
- Changing polling frequency or download flow
- Exposing `modified_at` in host UI (host already has richer metadata)
- Removing `updated_at` from the data model (keep for backward compat in daemon state)

## Decisions

### D1: Store `pptx_mtime` in daemon state alongside `last_exported_mtime`

`detect_changed_files()` already reads `pptx.stat().st_mtime` for comparison, but discards it. We store it as `pptx_mtime` in `daemon_state["files"][key]` at the point of detection (updating it whenever we re-scan). `_slides_from_state()` then maps `pptx_mtime → modified_at` in the response.

Alternative considered: derive it live from `pptx.stat()` at serve time — rejected because the PPTX path isn't always available at request time and this would add filesystem I/O to every `/api/slides` request.

### D2: `slides_cache_status` becomes a zero-payload invalidation event

Change `SlidesCacheStatusMsg` to remove the `slides` field. Daemon `_broadcast_slides_cache_status()` sends `{type: "slides_cache_status"}` only. Participant and host JS `case 'slides_cache_status':` handlers call the existing `GET /api/slides` (participant) / `_refreshHostSlidesCatalog()` (host) instead of processing inline data.

Alternative considered: keep payload for efficiency — rejected because the REST path already exists and is used on load; the WS-vs-REST divergence is the root cause of past bugs.

### D3: Participant renders `modified_at` directly, no fallback chain

Replace `slide.updated_at || slide.last_modified || ...` lookup in `_buildSlideItem()` with `slide.modified_at` only. The `updated_at` field stays in the data model but is no longer rendered on participant UI.

## Risks / Trade-offs

- [Risk] Participants/host on old JS code receiving the stripped WS message will silently do nothing on `slides_cache_status` → Mitigation: negligible — Railway auto-deploys static files; both JS and daemon deploy together on master push.
- [Risk] `pptx_mtime` will be `null` for uploaded slides (no PPTX on disk) → Mitigation: `modified_at` will be `null`; UI renders nothing (existing pattern for missing timestamps).
- [Risk] Slightly more REST calls after each `slides_cache_status` broadcast → Mitigation: acceptable; `slides_cache_status` fires rarely (only on download complete or status change), not on every WS message.

## Migration Plan

1. Update daemon: store `pptx_mtime`, expose `modified_at` in REST, strip `slides` from WS broadcast
2. Update participant.js: REST-refresh on WS trigger, render `modified_at`
3. Update host.js: REST-refresh on WS trigger (already has `_refreshHostSlidesCatalog()`)
4. Push to master — Railway deploys atomically; no backward compatibility window needed
