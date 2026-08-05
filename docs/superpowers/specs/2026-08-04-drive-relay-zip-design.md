> **STATUS: ABANDONED — 2026-08-05.** This was built, reviewed, deployed and then
> removed the same day. Keep the document: it records why the approach does not work,
> so nobody rebuilds it.
>
> **What killed it.** The relay authenticates to Drive with a plain API key, on the
> premise that "anyone with the link" folders are readable that way. That premise was
> verified for `files.get` and `files.list` — and silently assumed to extend to file
> *content*. It does not. Google answers `alt=media` content downloads for
> unauthenticated API-key requests with a 403 anti-abuse page ("your computer or
> network may be sending automated queries"), and trips it quickly on anything
> sizeable. A 285 KB folder succeeded in production; a real 6.8 MB course folder
> failed immediately.
>
> **Why it looked fine first.** The production verification used the smallest folder
> available — precisely the case that does not trip the limit. Verifying the happy
> path on the smallest input is not verifying the feature.
>
> **The second defect.** The 403 arrived after the response headers had been sent, so
> the streaming handler could only log it and stop. The participant received `200 OK`
> and a 0-byte archive that the browser reported as a completed download — a silent
> failure, on the exact audience that has no other way to get the materials.
>
> **What a real fix would need.** Authenticated downloads — a service account with its
> own project quota — not a retry loop, because this 403 is an anti-abuse block rather
> than transient throttling. The owner judged that setup not worth it.
>
> **What remains supported.** The participant materials-zip download built by the
> daemon from the local session folder (`daemon/materials/`, `railway/features/
> materials/`), which requires the trainer's daemon to be online.

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
| `drive_client.py` | Thin wrapper over Drive API v3 with an API key, on stdlib `urllib.request`: `get_metadata`, `list_children`, `open_download`. The only module that knows Google exists. |
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

### Resolved: Google returns the owner email

The open question was whether Google redacts `owners[].emailAddress` for
unauthenticated (API-key) requests. It does not. A `files.get` against a real
"anyone with the link" course folder, with an API key and no OAuth, returned:

```json
"owners": [{
  "displayName": "victorrentea",
  "permissionId": "04953412998680405404",
  "emailAddress": "victorrentea@gmail.com"
}]
```

So the gate runs on `DRIVE_OWNER_EMAILS=victorrentea@gmail.com`, and the
`DRIVE_ALLOWED_ROOT_IDS` fallback is not needed.

The gate still matches on **any populated identity field**, with
`DRIVE_OWNER_PERMISSION_IDS` available as a second configured identity. That is
not dead generality: `permissionId` is stable per account and costs nothing to
support, so if Google tightens redaction later the fix is a config change rather
than a code change. `displayName` is never accepted — it is user-settable.

## Zip streaming

**No new dependency.** `railway/` has five runtime dependencies and already downloads
from Drive with stdlib `urllib.request` (`railway/features/slides/cache.py:184`); this
feature stays inside that budget.

Stdlib `zipfile` can write into an unseekable stream: give `ZipFile` a small
`io.RawIOBase` sink that accumulates writes, use `zf.open(name, "w",
force_zip64=True)` to feed each file in chunks, and drain the sink after every chunk,
yielding what it collected. `ZipFile` detects the unseekable output and emits data
descriptors on its own, so zip-format correctness stays in the stdlib rather than in
our code. Downloads use `urllib.request` in the same sync style as `slides/cache.py`.
`StreamingResponse` receives the sync generator and Starlette runs it in a threadpool.

Verified before adopting: memory stays flat (largest single yield 64 KB regardless of
file size), the archive round-trips through Python's `zipfile`, and both `unzip` and
macOS `ditto` open it with unicode filenames intact.

Rejected alternatives: `stream-zip` (a dependency, for something the stdlib already
does here) and a hand-rolled zip writer (zip64 thresholds, data descriptors and
unicode flags are exactly where hand-rolled writers produce archives some tools
refuse to open).

Details:

- **STORED**, no compression. Materials are already PDF/PPTX/zip; compressing burns
  CPU for no gain.
- Subfolders are traversed recursively, structure preserved in the archive.
- Google-native files (Docs/Sheets/Slides) are exported via
  `/export?mimeType=application/pdf` and named `<name>.pdf`.
- Shortcuts resolved through `shortcutDetails.targetId`; trashed items skipped.
- A link to a **single file** streams that file directly, not a one-entry zip.
- Archive filename: `<folder name>.zip`.

### Size cap: 500 MB

`MAX_TRANSFER_BYTES = 500 * 1024 * 1024`, enforced twice, because one check cannot
be trusted:

1. **Before the transfer starts.** Sum the `size` field of every listed file; if it
   exceeds the cap, refuse with 413 and a clear message. This is the check that
   produces a good experience — the participant learns immediately instead of
   watching a download die.
2. **While streaming.** A running byte counter aborts the response if the cap is
   exceeded anyway. This is not redundant: Google-native files (Docs, Sheets, Slides)
   report **no `size`** in metadata, so their exported PDFs are invisible to check 1.
   A folder of a hundred Google Docs passes the pre-check at an estimated 0 bytes.

Check 1 counts an unknown-size file as 0 rather than guessing, and the preview
response flags `has_unsized_files` so the page can say the estimate is a lower bound.

Bandwidth is bounded by this cap together with rate limiting (see below).

## Exclusions

Session folders are mirrored to Drive as-is, so they carry files that exist for the
tooling, not for participants. The relay drops:

| Excluded | Why |
|---|---|
| `session-state.json` | Internal daemon state. |
| `attendees.md` | Participant names — nobody's download should contain the roster. |
| `Icon` and `Icon\r` | macOS custom-folder-icon file; `Icon\r` is its real name. |
| `~$*` | Office lock files. |
| `.obsidian/` (whole directory) | Editor configuration. |

Deliberately **not** excluded: `*.zip`. `daemon/materials/zip_builder.py` skips zips so
its own archive does not swallow a previous one; the relay has no such problem, and
`wiki.zip` is content a participant actually wants.

The list intentionally duplicates most of `daemon/materials/zip_builder.py` rather than
importing it: the two answer different questions ("what goes in the archive I build
from the local folder" vs "what goes in the archive I relay from Drive"), and they have
already diverged on `*.zip`. A shared constant would make the next divergence a
refactor instead of a one-line edit.

## Preview before download

`GET /api/drive/preview?url=...` validates the link, the ownership gate, the folder's
reachability and the size cap, then returns JSON: folder name, file count, total
bytes, and `has_unsized_files`.

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
| Owner is not the configured account | 404 | "This folder is not shared publicly, or the link is wrong" |
| Drive quota / 5xx | 502 | "Google Drive is not responding right now — please try again" |
| Folder over 500 MB (pre-check) | 413 | "This folder is larger than 500 MB — ask Victor to split it or send it another way" |
| Cap exceeded mid-stream | — | Archive is cut off at the cap; logged server-side as a pre-check miss. |
| Failure mid-stream | — | Truncated archive; unavoidable. Logged server-side, browser reports an incomplete download. |

A folder owned by someone else answers **404, not 403** — same status, same message as
a folder that does not exist. An earlier draft used 403 with a matching message, but
matching only the message still leaves the status code as an oracle: 403 fires solely
for folders that are real, public and owned by someone else, so an attacker could sort
folder ids into "Victor's" and "not Victor's" without reading the body at all.

The cost is accepted deliberately: when Victor himself pastes a folder he does not own,
he is told "not shared publicly, or the link is wrong", which is misleading. The server
log keeps the true reason.

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
- Folder whose listed sizes exceed 500 MB → 413 before any transfer.
- Folder of unsized native files whose exports exceed 500 MB → stream aborts at the
  cap (the pre-check cannot catch this one).
- **Daemon stopped → download still works** (the central requirement).
- No browser request to a Google host, and no 3xx response pointing at Google.

The REST contract joins the existing OpenAPI snapshot test.

## Setup (one-time, manual)

1. Google Cloud project → enable Drive API → create an API key, restricted *by API*
   (not by HTTP referrer — calls originate server-side).
2. Railway env: `GOOGLE_DRIVE_API_KEY`, `DRIVE_OWNER_EMAILS=victorrentea@gmail.com`.
3. The ownership spike determines whether `DRIVE_OWNER_PERMISSION_IDS` or
   `DRIVE_ALLOWED_ROOT_IDS` is also needed.
