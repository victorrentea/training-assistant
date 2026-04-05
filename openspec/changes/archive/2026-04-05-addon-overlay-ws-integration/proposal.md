## Why

The training daemon currently forwards emoji reactions to the desktop overlay via a fire-and-forget HTTP POST to `localhost:8765/emoji` — an endpoint that doesn't exist yet in `victor-macos-addons`. PowerPoint slide navigation is tracked by polling a file written by `powerpoint-monitor` every 3 seconds. A persistent WebSocket connection between the daemon and the addons WS server replaces both: it gives the daemon a reliable push channel for emoji animations and gives the addons app a real-time push channel for slide changes, eliminating the HTTP stub and the polling lag.

## What Changes

- **Existing**: WS server already provided by `victor-macos-addons` at port 8765 (`wispr-flow/ws_server.py`) — the daemon connects to it on startup.
- **Changed**: Daemon emoji router replaces the HTTP POST with a WS send through a persistent client connection to the bridge.
- **Changed**: Daemon slides module receives `slide` events over WS instead of reading the polling file, removing the 0.5-second file-read loop.
- **New**: `apis.md` section documenting the Daemon ↔ Addons WS protocol (message types, port, reconnect behaviour).
- **No change**: `start.sh` — the addons WS server is already launched by the addons startup sequence.
- **Changed**: Host UI ❤️ badge (`overlay-badge`) reflects whether the daemon's addon-bridge connection is active — connected (red) or disconnected (grey).

## Capabilities

### New Capabilities
- `addon-overlay-ws-bridge`: A WS server already running inside `victor-macos-addons` at port 8765 (`wispr-flow/ws_server.py`) that the daemon connects to; handles emoji forwarding to the overlay and real-time slide push to the daemon.

### Modified Capabilities
- `reactions`: Emoji delivery path changes from HTTP POST (unreliable, fire-and-forget, no server) to WS send over the persistent bridge connection.
- `slides`: Current slide source changes from file-polling (0.5 s interval) to WS push event from addons bridge.

## Impact

- `daemon/emoji/router.py` — replace `httpx` POST with a WS send
- `daemon/slides/` — remove file-read loop; add WS event handler for `slide`
- `daemon/__main__.py` — initialise and keep alive the addons WS client
- `apis.md` — new section: **Daemon ↔ Addons Bridge WS**
- `daemon/host_state_router.py` — include `overlay_connected` (bool) in host WS state messages
- `static/host.js` already consumes `overlay_connected` via `renderOverlayStatus()` — no JS change needed
- No database, no Railway changes, no participant-facing changes
