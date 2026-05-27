# Design: `files.md` — participant-facing file activity log

**Date:** 2026-05-27
**Status:** Approved (pending user review of written spec)
**Author:** Victor + Claude

## Background

The addon (running on the trainer's Mac) reports every file the trainer opens via a `GitFileOpenedMsg` WebSocket message (`url, branch, file, file_url`). Today the daemon:

- Accumulates these into a `git_repos` list inside `session-state.json`
- Exposes them at `GET /api/participant/git-activity`
- Renders them in a collapsible "Repos" entry in the participant left navbar (`static/participant.html:536-545`, `toggleRepos()` at `:1643-1678`)
- Surfaces a `git_files_count` field in the participant status payload

Two problems with the current design:

1. **Discoverability**: the collapsible navbar entry is hard to spot in an already-crowded sidebar; participants miss it.
2. **Transience**: the data lives only in the session-state JSON; participants who want to revisit a file mentioned earlier have no durable artifact.

## Goals

- Make the file list a first-class, easily-discoverable navbar entry that mirrors how AI summary / notes are presented.
- Persist the list as a human-readable markdown file (`files.md`) in the session folder, alongside `ai-summary.md`.
- Generate verified, stable GitHub links pointing to the **default branch only** (main or master), never feature branches.
- Show only **public** repositories — private repos are excluded entirely.
- Eliminate the `git_repos` entry from `session-state.json`. **All state for this feature lives in `files.md` itself.**

## Non-goals (v1)

- WebSocket push for live updates while the "Files" view is open (participant must reopen the view to refresh)
- GitHub PAT auth for higher rate limits (only if 60 req/hr unauthenticated proves insufficient in practice)
- Disambiguating same-named files across modules (handled by collision-downgrade — see below)
- Non-GitHub hosts (GitLab, Bitbucket) — silently dropped at ingestion

---

## Architecture

### Source of truth

`<session_folder>/files.md` is the canonical, self-sufficient store. The daemon parses it on load, mutates it per addon event, writes it back atomically. No parallel in-memory state needs to be persisted separately. `session-state.json` no longer carries `git_repos`.

### File format

```markdown
# Files opened this session

## [training-assistant](https://github.com/victorrentea/training-assistant) <!-- default_branch:master -->

- [participant.html](https://github.com/victorrentea/training-assistant/blob/master/static/participant.html) <!-- ts:2026-05-27T14:23:45Z path:static/participant.html -->
- utils.py <!-- ts:2026-05-27T14:25:01Z reason:ambiguous -->

## [some-other-public-repo](https://github.com/owner/some-other-public-repo) <!-- default_branch:main -->

- [README.md](https://github.com/owner/some-other-public-repo/blob/main/README.md) <!-- ts:2026-05-27T14:30:12Z path:README.md -->
```

**HTML comment metadata** (invisible to participants — see "Wire sanitization"):

- Repo `## [name](url) <!-- default_branch:<name> -->` — caches the GitHub default branch so the daemon doesn't re-query the GitHub API on every restart.
- Linked file `<!-- ts:<ISO8601> path:<within/repo> -->` — first-open timestamp + path within repo (used by collision detection).
- Unlinked file `<!-- ts:<ISO8601> reason:<code> -->` — first-open timestamp + reason for being unlinked. Reasons: `blob-404`, `ambiguous`, `no-path`, `rate-limited`.

### Empty state

A fresh session yields:

```markdown
# Files opened this session

No files opened yet
```

(No italics, per project rule. The string is plain text.)

### Dedup key

For every entry: `(repo_url, basename)`.

- Same basename in a repo only ever produces one bullet, regardless of source paths.
- File ordering within each repo section is chronological by first open (preserved by line order).
- Repo ordering is chronological by first repo-touched (preserved by section order).

### Privacy: public repos only

Repos that GitHub responds to with 404 or 403 (private, missing, or unauthenticated-access-denied) are **excluded entirely** from `files.md` — no section, no bullets. The daemon caches their private/missing status in an **in-memory** dict (not in `files.md`, since `files.md` only lists public repos) so it doesn't re-query during the session.

### Wire sanitization

The participant-facing endpoint (`/api/participant/files-md`) strips all `<!-- ... -->` HTML comments before sending. This keeps the internal metadata (default branch, `ts`, `reason`, `path`) out of the wire payload, since some comments could contain implementation-leaking detail and we want the participant-visible surface clean.

The on-disk file keeps full metadata.

---

## Components

### `daemon/files_md.py` (new)

Responsibilities:

1. **Parse** `files.md` into an in-memory representation: `{ repo_url: { default_branch, entries: [ {basename, link?, path?, ts, reason?} ] } }`.
2. **Append** entries with dedup + collision detection (see "Per-event sequence" below).
3. **Write** atomically: write `files.md.tmp`, `fsync`, `rename`.
4. **Render-sanitize**: strip HTML comments for the participant endpoint.

### `daemon/github_client.py` (new, tiny)

- `get_repo_info(owner, repo) -> RepoInfo | None` — `GET /repos/{owner}/{repo}`. Returns `{default_branch}` on 200, `None` on 404/403. Maintains an in-memory cache (process-lifetime).
- `head_blob(owner, repo, branch, path) -> bool` — `HEAD https://github.com/{owner}/{repo}/blob/{branch}/{path}` (or equivalent contents API call). Returns True iff 200.
- 3-second timeout per request. On rate-limit (403 with rate-limit headers), return a sentinel that callers map to `reason:rate-limited`.

### `daemon/addon_bridge_client.py` (modified)

Line 172 currently calls `participant_state.accumulate_git_file(...)`. Replace with `files_md.record_file_opened(url, branch, file_path, file_url)` for the active session.

### `GET /api/participant/files-md` (new endpoint)

Returns `text/markdown` body. Reads `files.md` from active session folder, strips comments, returns. Missing/empty file → returns the empty-state markdown above.

### Railway proxy (modified)

Add `/api/participant/files-md` to the dumb pass-through route list. Remove the existing pass-through for `/api/participant/git-activity`. Railway carries no feature-specific logic.

### Participant UI (`static/participant.html`)

- **Remove** the collapsible `gitrepos` nav entry (`:536-545`) and its `#repos-content` div.
- **Remove** `toggleRepos()` function (`:1643-1678`).
- **Add** a single non-collapsible `Files` nav entry in the same slot (similar icon — folder glyph).
- **Add** `#files-content` main-pane container alongside `#summary-content` / `#notes-content`.
- **Add** `loadFilesMd()` — fetches `/api/participant/files-md`, renders with `marked.parse(...)` using the existing custom link renderer (`target="_blank" rel="noopener"`).
- Wire `showView('files')` to call `loadFilesMd()`, same pattern as summary.
- No count badge.

### Status payload cleanup (`daemon/participant/router.py:141`)

Remove `git_files_count` field — no longer used.

---

## Per-event sequence

When the addon delivers a `GitFileOpenedMsg(url, branch, file, file_url)` for the active session:

```
1. Parse url → (owner, repo). If host != github.com → drop event, return.
2. Look up repo in cache:
   a. If known public → use cached default_branch.
   b. If known private/missing → drop event, return.
   c. If unknown → github_client.get_repo_info(owner, repo):
      · Returns RepoInfo → cache as public, store default_branch.
      · Returns None → cache as private, drop event, return.
      · Rate-limited → if the repo is ALREADY in files.md (= previously
        verified public), emit the file as unlinked `reason:rate-limited`
        under that section. If the repo is not yet in files.md, **drop
        the event entirely** — we can't prove the repo is public, so
        listing it would violate the privacy rule. Do NOT cache as
        public on rate-limit.
3. Compute basename = basename(file).
4. Look up (repo_url, basename) in files.md model:
   a. Not present →
      · If file path empty/null → write unlinked `reason:no-path`.
      · Else: head_blob(owner, repo, default_branch, file).
        - 200 → write linked bullet with path:<file>.
        - else → write unlinked `reason:blob-404`.
   b. Already linked, stored path == event path → no-op (already there).
   c. Already linked, stored path != event path → downgrade:
      rewrite bullet as unlinked `reason:ambiguous` (preserve ts).
      Skip the new event.
   d. Already unlinked → skip the new event.
5. If repo section doesn't exist yet → insert new `##` section appended
   at end of file before writing the bullet.
6. Atomic write to files.md.
```

---

## Migration

On daemon startup (and on session switch), for each session:

```
If session-state.json has `git_repos` key AND files.md does not exist:
  For each repo in git_repos:
    For each (file, file_url) in repo:
      Run the per-event sequence above (will verify against GitHub,
      will produce linked or unlinked entries as appropriate,
      will downgrade on natural collisions).
  Remove `git_repos` key from session-state.json, save.
```

This is idempotent and runs once per session. After migration, the on-disk source of truth is fully `files.md`.

---

## Testing

### Unit tests (`tests/daemon/test_files_md.py`)

- Parse round-trip: write known markdown, parse, verify model.
- Append linked file: produces expected markdown.
- Append unlinked file (each reason: `blob-404`, `ambiguous`, `no-path`, `rate-limited`).
- Dedup: same `(repo, basename)` reported twice → file unchanged.
- Collision-downgrade: linked entry, second event with different path under same basename → entry becomes unlinked `reason:ambiguous`, link stripped.
- Private repo (`get_repo_info` returns None) → no section, no bullets, no presence anywhere in `files.md`.
- Rate-limited repo lookup → file written as `reason:rate-limited`, repo not cached as public.
- Comment stripping for participant payload — assert no `<!-- ... -->` substrings remain.
- Atomic write — mock filesystem; assert `.tmp` + rename ordering.
- Migration: session-state.json with `git_repos` and no files.md → produces correct `files.md`, key removed from JSON.

### OpenAPI contract test

- New `/api/participant/files-md` present in `participant.openapi.yaml`.
- Old `/api/participant/git-activity` removed.
- `git_files_count` field removed from status payload schema.
- `API.md` regenerated.

### Hermetic Docker E2E (nightly if >5s)

- Two participants joined.
- Addon fires three `GitFileOpenedMsg`:
  - (a) public repo, valid path on default branch
  - (b) public repo, invalid path (will 404 on blob HEAD)
  - (c) private repo (mock GitHub to return 404 on `/repos/...`)
- Both participants click "Files".
- Assert rendered HTML contains public repo section with one linked + one unlinked bullet; private repo absent entirely.
- Assert network response body contains no `<!--` substring.

### Manual post-deploy verification

- Railway deploys to `interact.victorrentea.ro` on push.
- Trigger a real addon file event on `victorrentea/training-assistant`.
- Open `/` as participant, click Files, confirm working GitHub link to `master` branch.

---

## Code summary

**Added:**

- `daemon/files_md.py`
- `daemon/github_client.py`
- `GET /api/participant/files-md` route (in existing participant router or split file)
- `#files` nav entry + `#files-content` pane in `static/participant.html`
- `loadFilesMd()` JS function
- Railway proxy entry for `/api/participant/files-md`

**Modified:**

- `daemon/addon_bridge_client.py:172` — call site swapped from `accumulate_git_file` to `files_md.record_file_opened`
- Session loader — runs one-time migration

**Removed:**

- `daemon/participant/state.py:12-16` — `GitRepoActivity` model + `accumulate_git_file()`
- `daemon/participant/router.py:154-156` — `/api/participant/git-activity` endpoint + `GitActivityResponse`
- `git_files_count` field from participant status payload
- `participant.html:536-545` — `gitrepos` nav entry + `#repos-content`
- `toggleRepos()` JS function
- Railway proxy entry for `/api/participant/git-activity`
- `git_repos` key from each migrated session's `session-state.json`
