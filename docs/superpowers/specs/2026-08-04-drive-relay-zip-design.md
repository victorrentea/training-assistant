# Google Drive Relay — design

**Date:** 2026-08-04
**Status:** approved design, not yet implemented

## Problem

Some clients block Google Drive on their corporate network. After a workshop, Victor
emails participants a Google Drive folder link with the course materials; those
participants cannot open it.

They *can* reach `interact.victorrentea.ro`. So Railway — which is always online,
independent of the trainer's laptop — should fetch the Drive folder on their behalf
and stream it back as a zip.

## Scope

**In scope:** one public, session-independent endpoint plus a small page where a
participant pastes a Drive link and gets a zip.

**Out of scope:** distributing the link (Victor emails it himself), and the existing
`/api/materials/zip` feature (daemon zips the local session folder). Both stay as
they are. This is an additional, independent path.

## Non-negotiable constraints

1. **The participant's browser never contacts Google.** That is the entire point of
   the feature; a redirect to Drive would defeat it. See "Invariants" below.
2. **Works when the daemon is offline**, when no session is active, and when a
   *different* session is active. No WebSocket call to the daemon, no session state.
3. **Nothing written to persistent disk** — not even to ephemeral `/tmp`. The zip is
   produced as a stream.
4. **Not abusable as a free Drive downloader** for arbitrary public folders.

## Architecture

New self-contained component: `railway/features/drive_relay/`

| File | Responsibility |
|---|---|
| `link_parser.py` | Extract `(id, kind)` from a pasted URL. Pure function, no I/O. |
| `drive_client.py` | Thin wrapper over Drive API v3 with an API key: `get_metadata`, `list_children`, `open_download`. The only module that knows Google exists. |
| `ownership.py` | The anti-abuse gate. Pure decision function over metadata. |
| `zip_stream.py` | Generator yielding zip bytes as files stream in. Knows nothing about Drive or HTTP. |
| `router.py` | `GET /api/drive/preview`, `GET /api/drive/zip`, page route `/drive`. |
| `static/drive.html` | The page. |

Each unit is testable alone: `link_parser` and `ownership` are pure; `zip_stream`
takes an iterable of `(path, size, byte_iterator)` and is tested by reading its
output back with `zipfile`; `drive_client` is tested against the hermetic mock.

**Routing:** registered in `railway/app.py` **before** the `/{session_id}` catch-all,
which otherwise shadows root-level routes.

**Deployment note:** this touches `railway/**`, so unlike most changes in this repo it
triggers a real Railway deploy rather than shipping through the daemon.

## Link parsing

Accepted forms, all reduced to a Drive id:

- `https://drive.google.com/drive/folders/<id>` (with or without `?usp=sharing`)
- `https://drive.google.com/drive/u/0/folders/<id>`
- `https://drive.google.com/file/d/<id>/view`
- `https://drive.google.com/open?id=<id>`
- `https://docs.google.com/{document,spreadsheets,presentation}/d/<id>/...`

Anything else → 400. The parser does not guess: it matches known shapes and extracts
the id, rather than scanning for the first id-shaped substring.

## Anti-abuse gate

One check, on the pasted id only:

```
files.get?fields=id,name,mimeType,owners(emailAddress,permissionId,displayName),shortcutDetails,trashed
```

Accept iff some owner matches the configured identity: `DRIVE_OWNER_EMAILS` or
`DRIVE_OWNER_PERMISSION_IDS`.

Files *inside* an approved folder are not re-checked. If it sits in Victor's folder,
Victor vouched for it — and this correctly covers files other people placed there.

### Open risk and its resolution

Google may redact `owners[].emailAddress` for unauthenticated (API-key) requests.
The gate therefore matches on **any populated identity field**, and the **first
implementation step is a spike**: with a real API key, call `files.get` on one of
Victor's public folders and record which fields come back.

- `emailAddress` present → configure `DRIVE_OWNER_EMAILS`, done.
- only `permissionId` → configure `DRIVE_OWNER_PERMISSION_IDS` (stable per account).
- nothing identifying → **fallback plan**: configure `DRIVE_ALLOWED_ROOT_IDS` and
  walk the `parents` chain upward, accepting only descendants of those roots.

The architecture is unchanged in all three cases; only the source of identity moves.
This spike must run before the rest of the implementation.

## Zip streaming

`stream-zip` (one new dependency — battle-tested on zip64, unicode names, timestamps)
fed by a synchronous `httpx.Client` that downloads one file at a time.
`StreamingResponse` receives a sync generator, so Starlette runs it in a threadpool.
Memory stays constant; nothing touches disk.

Rejected alternative: hand-rolled async zip writer. It removes the dependency and the
threadpool, but zip-format edge cases (data descriptors, zip64 thresholds, unicode
flags) are exactly where hand-rolled writers produce archives that some tools refuse
to open.

Details:

- **STORED**, no compression. Materials are already PDF/PPTX/zip; compressing burns
  CPU for no gain.
- Subfolders are traversed recursively, structure preserved in the archive.
- Google-native files (Docs/Sheets/Slides) are exported via
  `/export?mimeType=application/pdf` and named `<name>.pdf`.
- Shortcuts resolved through `shortcutDetails.targetId`; trashed items skipped.
- A link to a **single file** streams that file directly, not a one-entry zip.
- Archive filename: `<folder name>.zip`.
- No size cap. Bandwidth is bounded by rate limiting instead (see below).

## Preview before download

`GET /api/drive/preview?url=...` validates the link, the ownership gate and the
folder's reachability, then returns JSON: folder name, file count, total bytes.

This exists so failures surface as a readable message on the page rather than as a
download that dies halfway through. `GET /api/drive/zip?url=...` re-runs the same
validation — preview is a convenience, never a trust boundary.

## Page

`static/drive.html`, served through `pages/router.py` (same CSP and OTel injection as
other pages). All UI text in English. One screen, three states:

1. **Input** — "Paste your Google Drive link" plus a button, disabled while the input
   is empty or whitespace-only (project convention).
2. **Preview** — folder name, file count, total size, "Download zip" button.
3. **Error** — explicit message, link preserved in the input so it can be corrected.

Downloading is a plain navigation to `/api/drive/zip?url=...`; the browser's native
download progress is used rather than a hand-built progress bar.

Visual polish is deliberately deferred to a follow-up pass.

## Errors

| Situation | Code | Participant sees |
|---|---|---|
| Unrecognized link | 400 | "That doesn't look like a Google Drive link" |
| Drive returns 404/403 | 404 | "This folder is not shared publicly, or the link is wrong" |
| Owner is not the configured account | 403 | "This folder is not shared publicly, or the link is wrong" |
| Drive quota / 5xx | 502 | "Google Drive is not responding right now — please try again" |
| Failure mid-stream | — | Truncated archive; unavoidable. Logged server-side, browser reports an incomplete download. |

The 403 message is deliberately identical to the 404 message so the endpoint cannot
be used as an oracle for which folders belong to Victor.

## Invariants (enforced by tests)

**No browser-to-Google traffic:**

- The relay follows Drive's redirects itself (`alt=media` on large files redirects to
  `drive.usercontent.google.com`) and forwards the bytes. It never returns a 3xx
  pointing at Google.
- The page contains no link, thumbnail or iframe to Drive. Error messages never
  suggest "open it in Drive".
- The CSP is left untouched — no Google host is added to `connect-src`/`img-src`, so
  a future regression is blocked by the browser as well as by tests.

## Rate limiting and logging

`/api/drive/zip` gets its own strict bucket built on the existing
`TokenBucketLimiter` (`railway/shared/rate_limit.py`): capacity 3, refill 1 per
5 minutes per IP. A participant downloading once never notices; a scraper stops
immediately. `/api/drive/preview` uses the ordinary probe limiter — it is cheap.

Logging under `[drive-relay]`: refusals, errors, and one line per download started
(client, folder, file count). Silence otherwise, per the project's logging
philosophy.

## Testing

**Unit:**
- `link_parser` across every accepted URL shape, plus junk input.
- `ownership` across each combination of populated and redacted identity fields.
- `zip_stream` — read the produced archive back with `zipfile`, assert structure,
  names and contents.

**Hermetic (Docker):** extend the existing `tests/docker/mock_drive_server.py` with
`files.list`, `alt=media` and `export` endpoints.

- Folder with subfolders → archive with the expected tree.
- Folder owned by someone else → 403.
- Google Doc → `.pdf` entry in the archive.
- **Daemon stopped → download still works** (the central requirement).
- No browser request to a Google host, and no 3xx response pointing at Google.

The REST contract joins the existing OpenAPI snapshot test.

## Setup (one-time, manual)

1. Google Cloud project → enable Drive API → create an API key, restricted *by API*
   (not by HTTP referrer — calls originate server-side).
2. Railway env: `GOOGLE_DRIVE_API_KEY`, `DRIVE_OWNER_EMAILS=victorrentea@gmail.com`.
3. The ownership spike determines whether `DRIVE_OWNER_PERMISSION_IDS` or
   `DRIVE_ALLOWED_ROOT_IDS` is also needed.
