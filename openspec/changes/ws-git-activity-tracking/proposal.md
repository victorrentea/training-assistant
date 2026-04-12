## Why

The current git activity tracking writes and reads a plain text file on disk, coupling the macOS addon to the daemon via a fragile shared filesystem path. This file-based mechanism must be replaced with WebSocket-based communication so that git activity is delivered reliably in real-time over the existing addon↔daemon WebSocket channel, eliminating file I/O and enabling the data to be stored in session state and served to participants.

## What Changes

- **macOS addon** sends a new `git_file_opened` WebSocket message to the daemon whenever the user opens a different file in IntelliJ (deduplicates against the last-sent value only).
- **Daemon** receives and accumulates `git_file_opened` events into the active session state (list of files per git-url+branch, no duplicates within a session).
- **Session state** stores accumulated git activity (`git_repos` list) and persists it to disk.
- **New REST endpoint** `GET /api/participant/git-activity` exposes the accumulated git repos to participants.
- **Host UI footer badge** (`⎇ N`) is kept working, now driven by the session state instead of the file.
- **BREAKING (removal)**: The `activity-git-YYYY-MM-DD.md` file writing/reading mechanism is removed entirely.

## Capabilities

### New Capabilities
- `git-activity-tracking`: Accumulate git file-open events from the macOS addon into session state and expose them via a participant REST endpoint.

### Modified Capabilities
- `addon-overlay-ws-bridge`: A new inbound WS message type (`git_file_opened`) is added to the addon bridge protocol.

## Impact

- `daemon/addon_bridge_client.py` — add handling for new inbound `git_file_opened` WS message.
- `daemon/host_state_router.py` — remove `_build_git_repos_fields()` file-reader; feed git activity from session state.
- `daemon/participant/router.py` — add `GET /api/participant/git-activity` endpoint.
- `daemon/participant/state.py` — add `git_repos` field to `ParticipantState`.
- Session state persistence (JSON on disk) — include `git_repos`.
- `static/host.js` / `static/host.html` — footer badge driven by session state / new endpoint.
- victor-macos-addons (external repo) — addon must emit `git_file_opened` WS message instead of writing file.
