## Context

Participant WS connect receives `{"type": "slides_cache_status", "slides_cache_status": {}}` — empty.

After the refactoring that moved PDF caching to the daemon:
- `state.slides_cache_status` in Railway is never populated (was populated by `seed_catalog_from_file()`, now removed)
- `_send_initial_messages()` pushes it to participants on WS connect → always empty dict
- `misc_state.slides_catalog` in the daemon is also never populated (`update_slides_catalog()` is defined but never called) → daemon's `GET /{session_id}/api/slides` always returns empty slides list

There are two separate issues: Railway wrongly owns state it cannot populate, and the daemon doesn't initialize its own state from the catalog file.

The correct fix aligns with the intended architecture: **daemon owns slides state**, participants pull from daemon via REST.

## Goals / Non-Goals

**Goals:**
- Participant sees correct slides list immediately on WS connect
- Daemon initializes `misc_state.slides_catalog` and `misc_state.slides_cache_status` on startup from catalog file + on-disk PDF check
- Participant JS calls `GET /api/slides` (proxied to daemon) on every WS connect to get initial state
- `_refreshSlidesCatalog` also applies `data.cache_status` to `_slidesCacheStatus`
- Railway removes `_send_initial_messages()` and its usage (Railway no longer manages slides state)
- WS daemon→participant broadcasts for live updates continue unchanged

**Non-Goals:**
- Changing the download flow or cache logic
- Changing the WS broadcast path for live updates

## Decisions

**Fix 1 — Daemon initializes misc_state on startup (`SlidesPollingRunner.start()`)**

Load catalog entries via existing `load_catalog_entries(cfg.catalog_file)`. For each entry, derive slug from `_slides_state["files"][_abs_key(source)]["slug"]` (from saved state) or fall back to `_slugify(Path(target_pdf).stem)`. Build `misc_state.slides_catalog` entries: `{slug, title, drive_export_url}`.

Also initialize `misc_state.slides_cache_status` for each slug by checking if the PDF already exists on the daemon's publish dir (`cfg.publish_dir / target_pdf`): `"cached"` if file exists, `"not_cached"` otherwise.

**Fix 2 — Participant JS fetches slides on WS connect**

In `ws.onopen`, add a call to `_refreshSlidesCatalog({ autoLoadSelected: true })` alongside the existing `/api/participant/state` fetch.

Also fix `_refreshSlidesCatalog` to apply `data.cache_status` to `_slidesCacheStatus` after the fetch (currently ignored).

**Fix 3 — Railway cleanup**

Remove `_send_initial_messages()` function and its call in `_handle_participant_connection`. Remove `state.slides_cache_status` updates from Railway's `cache.py` (or simply stop sending it — it's a no-op since it's always empty).

Note: `state.slides_catalog` in Railway is still used for the `download_pdf` WS flow (Railway downloads the PDF itself when triggered by daemon). That part stays untouched.

## Risks / Trade-offs

- Brief race: participant fetches slides immediately on WS connect, but daemon may not have loaded catalog yet on first ever startup. Acceptable — the REST call is retried implicitly on `slides_catalog_changed` WS message which Railway broadcasts when daemon connects.
- `_refreshSlidesCatalog` is also called on `slides_catalog_changed` — this is the existing path for daemon reconnects, and it continues to work correctly.
