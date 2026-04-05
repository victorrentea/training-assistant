## Why

Notes (`*.txt`) and key points (`ai-summary.md`) are currently fetched only via REST, so host and participants do not get immediate signals when content changes. During live sessions this causes stale UI and extra manual refreshes exactly when rapid feedback is needed.

## What Changes

- Add daemon-side file monitoring for the active session folder, covering:
- `ai-summary.md` (key points)
- the session notes text file (`*.txt`, assuming a single notes file per session)
- On file content change, publish WebSocket notifications to both participant and host channels.
- Include in each notification the computed non-empty line count for the changed document.
- Keep existing REST download endpoints as source of full content (`GET /{sid}/api/participant/notes`, `GET /{sid}/api/participant/summary`, `/api/{sid}/host/notes`, `/api/{sid}/host/summary`); WS only announces freshness + count.
- Update WS contracts/docs to include the new event and payload shape.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `notes_summary`: add real-time WS notifications (host + participants) when `ai-summary.md` or session notes `*.txt` changes, including non-empty line counts.

## Impact

- Daemon session/summary orchestration loop (file change detection and WS publish).
- Daemon WS message models/registries and corresponding contract tests.
- Host and participant real-time handlers (consume update event and trigger refresh UX).
- API/interaction documentation (`apis.md`, AsyncAPI WS docs if required by current contracts).
