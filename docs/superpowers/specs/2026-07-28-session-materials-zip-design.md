# Session Materials Zip — Download Without Google Drive

**Date:** 2026-07-28
**Status:** Approved for implementation
**Scope:** New Railway endpoints, daemon zip builder, participant sidebar entry

## Motivation

Participants currently reach the session materials through a single door: the **Google Drive** entry in the participant sidebar, which links to `gdrive_url` (`static/participant.html:793`). Some corporate clients block `drive.google.com` at the firewall, so for those participants that entry is dead — they can see it, click it, and get nothing.

They still reach `interact.victorrentea.ro` fine. So the fix is to serve the same content through the channel that already works: the Railway relay.

Google Drive offers no API for this. Drive API v3 has `files.get?alt=media` (one binary file) and `files.export` (Google-native docs only); there is no folder-zip endpoint. The zip produced by the Drive web UI comes from an internal, cookie-authenticated service with no stability contract. Every third-party tool that offers "download this folder" walks the tree and zips client-side.

We do not need any of that: the daemon already has the session folder on local disk, materialized by DriveFS at `~/My Drive/Cursuri/###sesiuni/<session>` (`daemon/config.py:96`). The daemon zips local files and pushes the archive to Railway. Google is never in the path.

### Traffic

Measured on the 2026-07-27..29 session folder:

| Item | Size |
|---|---|
| Session folder zipped (DEFLATE) | **130 KB** (216 KB raw) |
| Average slide deck PDF (24 files in `materials/slides/`) | 7.0 MB |
| Largest deck (`Clean Code.pdf`) | 15 MB |

Cost at **100% adoption**, 25 participants: 3.2 MB per session; ~325 MB/year at 100 sessions. At Railway egress rates that is cents per year. For comparison, one deck PDF served to one group already costs 175 MB — a full year of zip traffic is roughly two sessions' worth of slide traffic.

**Consequence for the design:** traffic is not a constraint. The feature is built for everyone, always visible, not gated behind "ask the trainer".

## Goals

1. Any participant can download the full session content as a zip, without reaching Google.
2. A visible download affordance in the sidebar, next to the existing Google Drive entry.
3. N simultaneous clicks produce one zip build, not N.
4. Participants who arrive after the daemon goes offline still get the last built zip.
5. A size guard so a stray large file in the session folder cannot turn into a traffic incident.

## Non-goals

- **No continuous mirror.** A `MaterialsMirrorRunner` existed and was deliberately removed in `dc1228ea` ("cleanup: remove materials mirror and endpoints"). It tick-synced `MATERIALS_FOLDER` file-by-file to Railway via `/api/materials/upsert` and `/api/materials/delete`. This design is not a revival of that: no background ticking, no per-file endpoints, no mirroring of `materials/` (293 MB). It is one on-demand archive of the *session folder* (~130 KB), built on participant demand. The name overlap is worth watching — see Naming below.
- No zipping of `materials/slides` or `materials/books`.
- No selective/partial download (all-or-nothing archive).
- No Google Drive API integration of any kind.
- No persistent storage guarantee on Railway — the zip is a cache, rebuilt on demand.

## Architecture

```
participant  ──GET /{sid}/api/materials/zip──▶  Railway
                                                  │
                                    fresh cache? ──yes──▶ FileResponse (attachment)
                                                  │no
                                    WS push {"type": "build_materials_zip"}
                                                  ▼
                                               daemon
                                          zip session folder (local disk)
                                                  │
                          POST /api/materials/zip/upload (multipart, host Basic auth)
                                                  ▼
                                    Railway stores + resolves pending Future
                                                  │
                                                  ▼
                                          FileResponse (attachment)
```

Two directions of daemon↔Railway traffic, each using an established mechanism:

- **Railway → daemon**: WS push, same as `MSG_FILE_READY_FOR_DOWNLOAD` (`railway/features/ws/daemon_protocol.py:29`), dispatched daemon-side through `ws_client.register_handler(...)` (`daemon/__main__.py:808`).
- **daemon → Railway**: multipart HTTP POST with host Basic auth, same as `railway/features/slides/upload.py:37`.

The WS proxy bridge (`railway/features/ws/proxy_bridge.py`) is deliberately **not** used to carry the archive: it does `body.decode("utf-8", errors="replace")` at line 39, so it cannot transport binary. The upload endpoint exists precisely to sidestep that.

## A. Daemon: zip builder

New module `daemon/materials/zip_builder.py`. (The `daemon/materials/` package directory survives from the removed mirror; its `__init__.py` is recreated.)

```python
def build_session_zip(session_folder: Path) -> bytes:
    """Walk session_folder recursively, DEFLATE everything except the exclusion set."""
```

**Exclusion set** (everything else is included):

| Pattern | Kind | Reason |
|---|---|---|
| `session-state.json` | exact name | internal daemon state |
| `attendees.md` | exact name | participant names |
| `Icon` | exact name | macOS Finder artifact (0 bytes) |
| `~$*` | glob | Office lock files |
| `*.zip` | glob | avoid nesting `wiki.zip` inside the archive |
| `.obsidian/` | directory | editor config, not content |

Arc names are relative to the session folder, so the archive expands into a clean tree.

**Size guard:** `MAX_ZIP_BYTES = 25 * 1024 * 1024`. Over the limit, the builder raises; the daemon logs a warning and reports failure rather than uploading. This guards against an unnoticed video or dataset in the session folder, not against normal growth.

**Handler** `handle_build_materials_zip(data, config)` in the same module, registered next to the existing upload handler:

1. Resolve the active session folder from `config.session_folder`.
2. Build the archive.
3. POST it multipart to `{config.server_url}/api/materials/zip/upload` with Basic auth from `config.host_username` / `config.host_password` (`daemon/config.py:83`), carrying `session_id` and `filename`.
4. On any failure (no session folder, size guard tripped, read error), POST `/api/materials/zip/upload` with no `file` part and an `error` form field carrying the message. Railway treats that as a failed build and rejects the pending Future immediately, so waiting participants fail fast instead of sitting out the full 20s timeout.

Filename sent to participants: the session folder name plus `.zip` — e.g. `2026-07-27..29 Spring+Quarkus@DB.zip`.

## B. Railway: endpoints, cache, dedup

New feature package `railway/features/materials/router.py`, mounted in `railway/app.py`.

### `GET /api/materials/zip` (public_router, under session prefix)

1. If a cached zip exists and is younger than `CACHE_TTL_S = 60`, serve it immediately.
2. Otherwise trigger a build and await it, bounded by `BUILD_TIMEOUT_S = 20`.
3. On timeout or daemon-reported error: serve the stale cached zip if one exists; otherwise `503`.
4. On success: `FileResponse` with `Content-Disposition: attachment; filename="<session>.zip"`, `Cache-Control: no-cache`.

**In-flight dedup** — a module-level `_pending_build: asyncio.Future | None`. The first request creates the Future and pushes the WS message; concurrent requests `await asyncio.shield(...)` on the same Future. This mirrors `_pending_refresh` in `railway/features/slides/router.py:25`, which solves the identical problem for slide PDFs. Without it, a group of 25 clicking at once would trigger 25 zip builds and 25 uploads from the trainer's laptop mid-session.

If `state.daemon_ws is None`, skip the push entirely: serve stale cache, else `503`.

### `POST /api/materials/zip/upload` (router, `Depends(require_host_auth)`)

Accepts multipart `session_id`, plus either `file` + `filename` (success) or `error` (failure, see A.4).

On success: streams to `.server-data/materials/<session_id>.zip` in 64 KB chunks with a `MAX_ZIP_BYTES` ceiling (same pattern as `railway/features/upload/router.py:55`), records the build timestamp, and resolves `_pending_build`.

On `error`: leaves any existing cache untouched and rejects `_pending_build` with the reported message.

A single `_pending_build` (not a per-session map) is sufficient — Railway serves one active session at a time, the same assumption `state.session_id` already encodes.

Storage is the existing ephemeral Railway disk. Losing the cache on redeploy is acceptable — the next request rebuilds it.

### Contracts

Per project convention, Pydantic models rather than raw dicts:

```python
class MaterialsZipUploadResponse(BaseModel):
    ok: bool
    size: int = 0
    filename: str = ""
```

New WS message constant `MSG_BUILD_MATERIALS_ZIP = "build_materials_zip"` in `railway/features/ws/daemon_protocol.py`.

## C. Participant UI

The Google Drive row is currently a single anchor ending in a dimmed `open_in_new` glyph (`static/participant.html:793`). A clickable element cannot be nested inside `<a target="_blank">` — invalid HTML, and the click would also navigate. The row becomes a flex wrapper holding two siblings:

```html
<div class="nav-item ..." id="gdrive-row">
  <a id="gdrive-nav" href="#" target="_blank" rel="noopener" class="flex-1 ...">
    <span class="material-symbols-outlined">cloud</span>
    <span class="text-base">Google Drive</span>
    <span class="material-symbols-outlined" style="font-size:1rem;opacity:0.5">open_in_new</span>
  </a>
  <button id="gdrive-zip-btn" title="Download everything as .zip">
    <span class="material-symbols-outlined">download</span>
  </button>
</div>
```

`download` is a Material Symbols glyph, matching the existing `cloud` / `open_in_new` / `commit` convention — no SVG asset needed.

**Visibility:** the whole row shows/hides on `gdrive_url` exactly as today. Both the initial-state path (`static/participant.html:3829`) and the WS-update path (`:3915`) set row visibility instead of anchor visibility.

**Click behavior:** swap the glyph for a spinner, `GET` the zip endpoint, restore on completion. Errors surface as a toast; the button never gets stuck spinning.

**Access-duration toast:** `_applyGdriveToast` (`static/participant.html:3303`) gains a second link pointing at the zip. That toast fires when the participant learns their access is time-limited — exactly when an offline copy is worth offering.

## Naming

`/api/materials/*` was the namespace of the removed mirror (`/api/materials/upsert`, `/api/materials/delete`). The new paths are `/api/materials/zip` and `/api/materials/zip/upload` — no collision with the deleted routes, and "materials" is the term participants see. Implementation keeps the distinction explicit in module docstrings so this is not mistaken for the mirror returning.

## Error handling

| Condition | Behavior |
|---|---|
| Daemon WS not connected | stale cache if present, else `503` |
| Daemon build times out (>20s) | stale cache if present, else `503` |
| Zip exceeds 25 MB | daemon logs warning, reports error, does not upload; participant gets stale cache or `503` |
| No active session folder | daemon reports error; `503` |
| Upload auth failure | `401` from `require_host_auth`; daemon logs it |

Every failure path prefers serving something slightly stale over failing, because a participant hitting this button usually has no working alternative.

## Testing

**Unit (`tests/daemon/`)**
- Zip builder honors every exclusion rule; included files keep correct relative arc names.
- Size guard raises above the ceiling.
- Empty/missing session folder is handled.

**Railway feature tests (`tests/features/materials/`)**
- Fresh cache served without any WS push.
- Concurrent requests trigger exactly one WS push (dedup).
- Daemon disconnected + stale cache present → stale served, not `503`.
- Daemon disconnected + no cache → `503`.
- Upload endpoint rejects unauthenticated calls and oversized bodies.

**Hermetic E2E (`tests/docker/`)**
- Full round trip: participant clicks download → daemon builds → Railway serves → response is a valid zip whose entries match the expected set, and excluded files are absent.

**Proof for the task**: screenshot of the sidebar row with the download glyph, plus a passing `bash tests/check-all.sh`.

## Deployment

- `railway/**` changes → this triggers a **real Railway redeploy**, unlike most changes to this repo.
- `daemon/**` and `static/**` ship automatically on push to `master` via daemon restart + `static_sync`.
- `API.md` regenerated via `python3 scripts/generate_apis_md.py --output API.md` (never edited by hand).
- `ARCHITECTURE.md` updated with the new flow.
