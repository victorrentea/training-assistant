# Open files: accurate git linking, deferred relink, and tree rendering

**Date:** 2026-08-04
**Status:** approved design, not yet implemented

## Problem

The participant-facing "Files" tab lists the files opened in IntelliJ during a session. Two things are wrong with it.

**The links point at the wrong code.** The IntelliJ plugin already captures the exact repo-relative path and the current branch, but the daemon throws both away and re-derives the path by matching the *basename* against the GitHub **default branch** tree. A file edited on a workshop branch links to master's version of it — sometimes a different file entirely, sometimes nothing at all (`ambiguous`, `not-in-repo`).

**The list is hard to read.** Six files from the same package render as six lines each carrying the same 40-character path prefix.

A third need drives the first: the training summarizer must be able to cite the file a summary section is about. At the moment a file is opened it may not be committed or pushed yet, so its link cannot be resolved live — but by summarization time it usually can.

## Current state

| Component | Where | What it does today |
|---|---|---|
| IntelliJ plugin | `live-coding/…/openfile/OpenFileReporter.kt` | After a 5s dwell on a file in a focused IDE window, resolves the repo via `git4idea` and POSTs `{url, branch, file, project}` to `http://127.0.0.1:55123/intellij/file-opened`. `file` is the path relative to the git root. Gated by `AppSettingsState.reportOpenFileToAddon`, **default `false`**. |
| macOS addon | `victor-macos-addons/…/AppDelegate.swift:1123` | Receives the POST, normalizes the remote to https, forwards over the local WS bridge as `git_file_opened`. Deliberately passes `fileURL: nil` — comment: *"Daemon ignores branch/fileURL"*. |
| macOS addon | `victor-macos-addons/…/IntelliJMonitor.swift` | AppleScript window-title scraper, the pre-plugin capture path. **Already disabled** — `ijMonitor.start()` is commented out at `AppDelegate.swift:1118`. |
| Daemon | `daemon/addon_bridge_client.py:29` | Reads only `url` and `file` from the message; `branch` is dropped on the floor. |
| Daemon | `daemon/files_md.py` | Keys entries by basename, resolves against the GitHub default branch tree, downgrades to unlinked on basename collision, retries unresolved entries on every load. Stores the **first** open timestamp in UTC. |
| Participant UI | `static/participant.html:5083` (`loadFilesMd`) | `marked.parse` of the raw markdown; a post-pass greys the directory prefix of each link. Flat list. |
| Summarizer | `~/workspace/ai/skills/training-summarizer/SKILL.md:14` | References the artifact by its old name `files.md` (renamed to `opened-files.md`). |

So the capture pipeline exists and is accurate end-to-end up to the daemon's front door. The work is to stop discarding the good data, defer the unresolvable cases to summarization time, and render a tree.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Link target | The branch captured at open time, falling back to the default branch | Faithful to what was on screen during the workshop. |
| Fallback ladder | captured branch → default branch → no link | Three states, no guessing. No search across other remote branches (would send participants to a branch never shown), no basename re-matching (that is exactly the heuristic being removed). |
| Who repairs stale links | One explicit pass, invoked by the summarizer | No background retry loop to reason about. Links resolve at open time when they can; the rest are repaired once, right before they matter. |
| Transport | Unchanged: plugin → addon HTTP → addon WS bridge → daemon | Already built and working. The addon stays the single funnel for machine-local events. |
| AppleScript scraper | Deleted | Already dormant. Keeping a second, lower-fidelity source alive would mean a precedence rule and two formats. |
| Storage shape | Flat — one line per file, full path | Link-checker subagents want greppable full paths. The tree is a participant need, not a file-format need. |
| Grouping | One `##` block per repo; each entry carries the branch of its last open | A file is one row wherever you opened it. Splitting the repo into a block per branch would show the same file twice and fragment the tree for a case that is rare in practice. |
| Timestamp | Last open, rendered in the daemon machine's timezone, stored as UTC | The visible time answers "when did we look at this last". UTC storage survives DST. |
| Plugin safety | Circuit breaker driven by the POSTs it already makes | The setting is already opt-in; the breaker covers someone enabling it on a machine with no addon. |

## Storage format

`opened-files.md`, in the session folder. Serving to participants still strips HTML comments via `sanitize_for_wire`.

```markdown
# Files opened this session

## [clean-code-java](https://github.com/victorrentea/clean-code-java) — branch `master` <!-- branch:master default_branch:master -->

- [src/main/java/victor/training/cleancode/ComplexIfs.java](https://github.com/victorrentea/clean-code-java/blob/master/src/main/java/victor/training/cleancode/ComplexIfs.java) — 09:41 <!-- ts:2026-08-04T06:41:07Z path:src/main/java/victor/training/cleancode/ComplexIfs.java branch:master ref:branch -->
- [src/main/java/victor/training/cleancode/Immutability.java](https://github.com/victorrentea/clean-code-java/blob/solved/src/main/java/victor/training/cleancode/Immutability.java) — 10:05 · branch `solved` <!-- ts:2026-08-04T07:05:12Z path:src/main/java/victor/training/cleancode/Immutability.java branch:solved ref:branch -->
- src/main/java/victor/training/cleancode/Draft.java — 11:20 <!-- ts:2026-08-04T08:20:31Z path:src/main/java/victor/training/cleancode/Draft.java branch:master reason:not-pushed -->
```

Rules:

- One `##` heading per repo. Heading comment carries `branch:` — the branch of the **most recent** open anywhere in that repo — and `default_branch:` (cached from the GitHub API).
- Entry key: **(repo, path)**. Re-opening a file updates its timestamp *and* its branch in place; it never appends a second line. A file opened on `master` and later on `solved` is one row, pointing at `solved`.
- Each entry stores its own `branch:`. When it differs from the heading's branch, the **visible** text gains ` · branch \`<name>\`` after the time. This matters: `sanitize_for_wire` strips every HTML comment before the document reaches a participant, so anything the UI must display has to live in the visible text, not in a comment. Entries on the heading's branch say nothing — the heading already does.
- Link text is the full repo-relative path. Unlinked entries render the same path as plain text.
- `ts:` is the **last** open, ISO-8601 UTC, second precision. The visible `HH:MM` is derived at write time in the daemon machine's local timezone — the daemon runs on that machine, so `datetime.now().astimezone()` is the right clock.
- If every entry in the document falls on the same local calendar date, times render as `HH:MM`. If any two differ, **all** entries in that document render as `MMM D HH:MM` (multi-day sessions exist, e.g. folder `2026-07-09..10`). The format is uniform within a file — never mixed. Adding an entry on a new day therefore rewrites the visible times of the existing ones; the canonical `ts:` values are untouched.
- `ref:` records which reference resolved the link: `branch` or `default`. Diagnostic only (comment-only, never seen by participants), and asserted in tests.
- `reason:` on unlinked entries, mutually exclusive and checked in this order:
  - `no-branch` — the captured branch does not exist on GitHub, **and** the path is absent from the default branch.
  - `not-pushed` — the captured branch exists but does not contain the path, **and** the default branch does not either.
  - `rate-limited` — the GitHub API was rate-limited, so neither ref could be checked.

Everything that existed to support basename guessing is deleted: `paths_by_basename` lookups in `files_md`, the `ambiguous` reason, the collision-downgrade branch, `_upgrade_unlinked_entries`, and `_NOISE_BASENAMES` (the `✻` spinner character leaked in through window-title scraping, which no longer exists).

The privacy rule is unchanged: a repo that the GitHub API reports as private or 404 is dropped entirely — the event is never recorded. When rate-limited, an event is only recorded if its repo is already present in the document (i.e. previously verified public).

## Component changes

### `live-coding` (IntelliJ plugin)

`OpenFileReporter` gains a circuit breaker. No change to the payload or the endpoint.

- A counter of consecutive POST failures. On the 3rd, the reporter enters a backoff state.
- While backed off, `report()` skips the POST unless at least 5 minutes have passed since the last attempt; then it lets exactly one attempt through.
- Any successful POST resets the counter and clears the backoff.
- No extra thread, no separate probe: a connect to `127.0.0.1` with no listener is refused immediately (`ECONNREFUSED`, not a timeout), so the POST that was going to happen anyway *is* the liveness check.
- Cost on a machine without the addon, with the setting mistakenly enabled: roughly a dozen refused connections per hour.
- Recovery on Victor's machine: if IntelliJ starts before the addon, reporting resumes within 5 minutes with no IDE restart.

### `victor-macos-addons`

- Delete `Sources/VictorAddons/IntelliJMonitor.swift`, the `ijMonitor` property, its construction and the commented-out `start()` call in `AppDelegate.swift`.
- `IntelliJMonitor.httpsRemote(_:)` is still used by the plugin-POST handler — move it to a small `GitRemote` helper (or onto `TabletHttpServer`) so deleting the monitor does not take it down.
- Drop the `fileURL` parameter from `LocalWebSocketServer.pushGitFileOpened` and the `file_url` key from the message it builds. The only remaining caller already passes `nil`, and the daemon builds the URL itself. `GitFileOpenedMsg.file_url` stays declared and optional on the daemon side, so an older addon binary still validates.

### `training-assistant` (daemon)

- `daemon/addon_bridge_client.py::_handle_git_file_opened` reads `branch` and passes it through. An empty or missing branch (detached HEAD, or an addon that predates this change) means "no captured branch": resolution skips straight to the default branch, and the entry stores the default branch as its own.
- `daemon/files_md.py`:
  - `Repo` gains `branch` (the most recent open in that repo); `Doc.find_repo` still keys on url alone.
  - `Entry` drops `basename` as the identity field (keep it as a derived property for display if useful), and gains `branch`; `path` is now always known — it comes from the plugin.
  - `record_file_opened(url, branch, path)` resolves as described below and upserts by (repo, path), overwriting the entry's branch and timestamp, and refreshing the repo heading's branch.
  - Render/parse handle the new heading and entry formats, and the old ones (see Migration).
  - `count_open_files` unchanged in behaviour.
- New module `daemon/relink_open_files.py`, runnable as `python3 -m daemon.relink_open_files`:
  - `--session-folder <path>` targets a specific session; without it, the active session.
  - Re-resolves **every** entry from scratch, including currently-linked ones, so a link made on a since-deleted branch degrades correctly.
  - Prints a JSON summary to stdout: `{"repos": n, "entries": n, "linked_branch": n, "linked_default": n, "unlinked": n}` so the summarizer skill can report what it did.
  - Exit code 0 even when some entries stay unlinked — that is a normal outcome, not a failure.

### Resolution algorithm

Used identically at open time and by the relink pass:

1. Canonicalize the remote to `https://github.com/OWNER/REPO`; drop non-github.com hosts.
2. `get_repo_info(owner, repo)` → `None` means private or 404 → drop the event entirely. Rate-limited → proceed only if the repo block already exists (it was verified public earlier); use its cached `default_branch`, record the entry unlinked with `reason:rate-limited`, and stop here.
3. If a captured branch exists, check whether `path` is present on it (repo tree when available and untruncated, else a blob `HEAD`). Hit → link with `ref:branch`.
4. Otherwise check the same `path` on the default branch. Hit → link with `ref:default`.
5. Otherwise record unlinked with `reason:no-branch` if the captured branch itself is missing from GitHub, else `reason:not-pushed`.

### `static/participant.html`

`loadFilesMd` stops relying on `marked` for the list structure. It parses the sanitized markdown (comment-free, so it works from the visible text alone) into `{repo, url, branch, entries[{path, href, time, branch}]}`, builds a tree per repo block, and renders it.

The tree builder must be a **top-level named function** in `static/participant.html` — e.g. `function buildFileTree(paths)` — because `tests/test_participant_js.js` extracts such functions verbatim from the shipped file and exercises them under plain `node`. A closure or an inline arrow cannot be tested that way.

Tree construction:

1. Split each entry's path on `/` and insert into a trie; leaves are files, interior nodes are folders.
2. **Collapse chains:** a folder node that holds no files of its own **and** has exactly one child, and that child is a folder, merges with its child (`main` + `java` + … → `main/java/victor/training/cleancode`). The "no files of its own" condition prevents orphaning a file. Applied repeatedly until no node qualifies.
3. **Sort** within every node: folders first, then files; each group alphabetically, case-insensitive.
4. Render with one indent step per level. Folder rows are non-interactive; file rows are the link (or plain text when unlinked) followed by the grey time, immediately after the name — not right-aligned. When the line carries a trailing ` · branch \`x\``, it renders as a small chip after the time.

`src` therefore stays a visible node whenever it branches into `main` and `test`, costing one indent level. That is the accepted trade-off over a flatter but dishonest tree.

Repo heading shows the repo name plus its branch as a chip.

### `~/workspace/ai/skills/training-summarizer`

- New first step, before anything else: run `python3 -m daemon.relink_open_files --session-folder <folder>` and report its JSON summary. This is what lets later steps cite files by URL.
- Fix the stale artifact name: `files.md` → `opened-files.md` (SKILL.md:14).
- State explicitly that link-verification subagents may consult `opened-files.md` to attach a section to the file it discusses.

## Migration

Existing session folders hold the old format: basename-keyed entries, headings without `branch:`, `ts` = first open.

- The parser accepts old headings (no `branch:` comment) by treating the block's branch — and every entry's branch — as the repo's default branch.
- Old entries that carry a `path:` comment migrate cleanly — path becomes the key, `ts` is reinterpreted as "last known open".
- Old entries **without** a `path:` (the `ambiguous` / `not-in-repo` leftovers) are dropped on the first save. They were never linkable and their basename alone cannot be recovered into a path. **Approved by the user.**
- No separate migration script: conversion happens the first time a document is loaded and saved, including by the relink pass. `migrate_session_if_needed` (the `session-state.json` → markdown one-shot) is unaffected.

## Testing

- `tests/daemon/test_files_md.py`: format round-trip for the new heading and entry shapes; upsert-by-path on re-open updates the timestamp and branch instead of appending, and refreshes the repo heading's branch; `ref:branch` when the file exists on the captured branch; `ref:default` when it does not; unlinked with `reason:not-pushed` when it exists on neither; old-format parse and the drop of path-less entries; `HH:MM` vs `MMM D HH:MM` selection with a frozen clock and a fixed timezone.
- New `tests/daemon/test_relink_open_files.py`: full re-resolution including the degrade path (a previously linked entry whose branch has disappeared) and the JSON summary shape.
- `tests/test_participant_js.js` gains cases for `buildFileTree`: chain collapse, the "no files of its own" guard that must *not* collapse, folders-before-files ordering, case-insensitive sort, and a single root-level file. Run by CI at `.github/workflows/ci.yml:29` (`node tests/test_participant_js.js`); note that `tests/check-all.sh` does **not** run it, so run it by hand before pushing.
- Visual proof: screenshot of the participant Files tab with a multi-package, multi-folder session.
- `bash tests/check-all.sh` before the push, per the pre-push hook. `tests/docker/mock_github_server.py` already exists for tests that need GitHub responses.
- The WS contract (`GitFileOpenedMsg`) is unchanged — `branch` is already declared — so no `API.md` regeneration and **no Railway deploy** is required. Static and daemon changes hot-deploy on push to `master`.

## Out of scope

- Pinning links to commit SHAs.
- Searching other remote branches or git history for renamed/moved files.
- Any change to the Railway relay.
- Reporting open files from editors other than IntelliJ.
