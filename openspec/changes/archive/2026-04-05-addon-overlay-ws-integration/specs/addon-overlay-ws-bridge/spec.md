## ADDED Requirements

### Requirement: Daemon WS client connects to addons server with reconnect
The training-assistant daemon SHALL include an `addon_bridge_client` that connects to `ws://127.0.0.1:8765` on startup and reconnects automatically after any disconnect. The addons WS server is already implemented at `wispr-flow/ws_server.py` and requires no changes. On connect, the server immediately sends the last known slide state as a welcome message.

#### Scenario: Successful connection
- **WHEN** the daemon starts and the addons WS server is running at port 8765
- **THEN** the client connects within 5 seconds and receives the last known slide state as a welcome message

#### Scenario: Server not running at startup — graceful retry
- **WHEN** the daemon starts but the addons WS server is not yet running
- **THEN** the client retries with exponential back-off (max 30 s interval) until the server becomes available; no error is shown to participants

#### Scenario: Connection lost mid-session
- **WHEN** the addons WS server crashes or is restarted
- **THEN** the daemon client detects the disconnect and reconnects automatically

---

### Requirement: Daemon sends emoji over WS to addons server
When the daemon receives a participant emoji reaction, it SHALL send an `emoji` message over the persistent WS connection to the addons server, which relays the animation to the overlay.

#### Scenario: Emoji sent and animated
- **WHEN** a participant sends an emoji reaction
- **THEN** daemon sends `{"type": "emoji", "emoji": "❤️", "count": 1}` to the addons WS server and the desktop overlay animates the emoji on screen

#### Scenario: Addons server not connected — no crash
- **WHEN** daemon tries to send an emoji but the WS connection is not active
- **THEN** the daemon logs a warning and continues without raising an error

---

### Requirement: Daemon handles slide event from addons server
The addons WS server SHALL push a `slide` message to the daemon whenever the current slide or deck changes. The daemon SHALL update `slides_current` state immediately on receipt.

#### Scenario: Slide navigation detected
- **WHEN** the presenter moves to a different slide in PowerPoint
- **THEN** the addons server sends `{"type": "slide", "deck": "<deck name>", "slide": <slide_number>, "presenting": <bool>}` to the daemon

#### Scenario: Welcome message on connect
- **WHEN** the daemon connects to the addons WS server
- **THEN** the server immediately sends the last known slide state as the first message

---

### Requirement: Host UI ❤️ badge reflects addon-bridge connection state
The daemon SHALL include `overlay_connected: bool` in every host WS state message it sends. The host UI SHALL render the `overlay-badge` (❤️) as connected (coloured) when `overlay_connected` is `true`, and disconnected (grey) when `false`. The `renderOverlayStatus()` function in `host.js` already handles this rendering — no JS change is needed beyond the daemon sending the field.

#### Scenario: Bridge connected — badge lit
- **WHEN** the daemon's addon-bridge WS client is connected to the addons server
- **THEN** host receives `overlay_connected: true` and the ❤️ badge renders as connected (red/coloured)

#### Scenario: Bridge not connected — badge grey
- **WHEN** the daemon's addon-bridge WS client is disconnected or has not yet connected
- **THEN** host receives `overlay_connected: false` and the ❤️ badge renders as disconnected (grey)

#### Scenario: Badge updates dynamically on connection change
- **WHEN** the bridge connects or disconnects mid-session
- **THEN** the daemon sends an updated host WS state push with the new `overlay_connected` value within 1 second, and the badge updates without page reload
