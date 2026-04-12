## Context

The macOS addon currently appends lines to `activity-git-YYYY-MM-DD.md` on disk whenever the user opens a file in IntelliJ. The daemon reads this file on each host state request via `_build_git_repos_fields()`, parsing timestamped lines with a regex. This couples addon and daemon through a shared filesystem path and prevents the data from being surfaced to participants (who connect to Railway, not the daemon's local filesystem).

An existing persistent WebSocket connection already runs between the macOS addons server (`ws://127.0.0.1:8765`) and the daemon (`addon_bridge_client.py`). The addons server already sends structured JSON messages for slides. Git file-open events should use the same channel.

## Goals / Non-Goals

**Goals:**
- Replace file I/O with a new `git_file_opened` WS message sent from the addon to the daemon.
- Accumulate git activity (url, branch, files) in `ParticipantState` with per-session deduplication.
- Persist git activity as part of the session state JSON on disk.
- Expose accumulated git activity via `GET /api/participant/git-activity`.
- Keep the host footer `⎇ N` badge working, sourced from session state rather than the file.
- Remove the `activity-git-*.md` file writing/reading completely.

**Non-Goals:**
- Changing the addon's internal IntelliJ plugin logic beyond the WS message it sends.
- Showing git activity on the participant page UI (this change is data/API only).
- Streaming real-time updates to participants via WebSocket (polling the endpoint is enough).

## Decisions

### D1 — New inbound WS message type `git_file_opened`
The addon sends `{"type": "git_file_opened", "url": "<git-url>", "branch": "<branch>", "file": "<file-path>"}` when the user opens a different file. The addon deduplicates against its last-sent message only (stateless beyond that). The daemon accumulates without further deduplication on the transport — it deduplicates at the state level (set per url+branch).

**Alternative considered:** a dedicated HTTP POST endpoint on the daemon. Rejected: the WS connection is already open and the addon communicates exclusively over it; adding REST would require auth, connection management, and a different lifecycle.

### D2 — State storage in `ParticipantState.git_repos`
`git_repos: list[GitRepoActivity]` is added to `ParticipantState`. `GitRepoActivity` is a Pydantic model: `{url: str, branch: str, files: list[str]}`. Files within each (url, branch) entry are stored as an ordered list of unique values (insertion order, no duplicates).

**Alternative:** a separate state singleton. Rejected: git activity is session-scoped, and `ParticipantState` is already the session-level container persisted to disk.

### D3 — `GET /api/participant/git-activity` returns the full accumulated list
The endpoint returns `{"git_repos": [{url, branch, files}, ...]}`. It requires no auth and is accessible to any participant UUID (same as `/api/participant/state`). The host also calls this endpoint (or reads the same state) for the footer badge count.

**Alternative:** include `git_repos` in the existing `/api/participant/state` response. Rejected: the state response is already large; git activity is ancillary and polling it separately avoids bloating every state fetch.

### D4 — Host footer badge sourced from host state WS push
The daemon continues to include `git_repos_count` (and optionally `git_repos`) in the host WS state push message, sourced from `participant_state.git_repos` instead of the file. No host JS change is needed — the badge already reads `msg.git_repos_count`.

## Risks / Trade-offs

- **Addon not yet updated** → daemon receives no `git_file_opened` messages; git activity stays empty. Not a regression: the file mechanism is removed, but the feature simply shows zero until the addon is updated.
- **Session state growth** → a session with hundreds of files opened will accumulate a large list. Acceptable: git file paths are short strings; thousands of entries are still kilobytes.
- **WS reconnect gap** → if the addon reconnects mid-session, it only resends the last-opened file. Previously opened files in the gap are lost. Acceptable: the requirement explicitly states the addon does not need to remember more than the last sent message.

## Migration Plan

1. Deploy daemon with new WS message handler + session state field + REST endpoint.
2. Update macOS addon to emit `git_file_opened` instead of appending to file.
3. Remove `_build_git_repos_fields()` and file-read path from daemon.
4. Delete any stale `activity-git-*.md` files from the addons-output folder (optional cleanup).

Rollback: revert the daemon commit; the addon falls back to file writing if the daemon no longer handles the new message (it will simply be ignored by an older daemon).
