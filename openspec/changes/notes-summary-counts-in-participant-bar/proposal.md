## Why

The participant `/state` response was shipping the full notes text and all summary points on every page load, wasting bandwidth and slowing the initial render. Participants also had no live signal when notes or the AI summary gained new content during a session.

## What Changes

- `/state` endpoint returns `notes_count` (non-empty line count) and `summary_count` (point count) instead of the full `notes_content` and `summary_points` arrays.
- Daemon broadcasts `notes_updated {count}` and `summary_updated {count}` over WebSocket to all participants and the host whenever the notes file or `ai-summary.md` changes on disk.
- Participant header Notes and Key Points buttons are enabled/disabled based on these counts and display the count in the button label.
- On receipt of a `notes_updated` or `summary_updated` WS message the count in the button label updates with a yellow highlight flash.
- Full notes/summary content is still fetched on demand when the participant clicks the button.
- Host notes badge and summary badge likewise reflect the daemon-pushed counts.

## Capabilities

### New Capabilities

- `notes-summary-counts`: Real-time count badges for notes and AI summary in participant and host bars, driven by WS push from daemon.

### Modified Capabilities

- `notes_summary`: Participant state contract changes — full content replaced by integer counts; WS push messages added.

## Impact

- `daemon/participant/router.py` — `/state` response shape
- `daemon/ws_messages.py` — two new Pydantic message types
- `daemon/__main__.py` — broadcast on probe change and on WS reconnect
- `railway/features/ws/router.py` — forwards broadcasts; no new Railway state
- `static/participant.js` — state handler + WS handler update counts + flash
- `static/host.js` — WS handler updates notes badge and summary badge counts
- `docs/participant-ws.yaml`, `docs/host-ws.yaml` — new message types
- `apis.md` — updated contract
- `tests/docker/` — new hermetic test for count display and WS flash
