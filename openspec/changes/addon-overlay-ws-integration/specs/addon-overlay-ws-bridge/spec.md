## ADDED Requirements

### Requirement: WS server runs in addons on port 56789
`victor-macos-addons` SHALL include an `addon-bridge` Python module that starts an asyncio WebSocket server on `localhost:56789`. The server SHALL accept multiple simultaneous connections (typically one: the daemon).

#### Scenario: Server starts successfully
- **WHEN** `addon-bridge` is launched
- **THEN** a WebSocket server is listening on `ws://localhost:56789/ws`

#### Scenario: Multiple reconnects accepted
- **WHEN** the daemon disconnects and reconnects
- **THEN** the bridge accepts the new connection without restart

---

### Requirement: Bridge forwards emoji_reaction to overlay
When the bridge receives an `emoji_reaction` message from the daemon, it SHALL trigger the desktop overlay to display the animation.

#### Scenario: Emoji received and animated
- **WHEN** daemon sends `{"type": "emoji_reaction", "emoji": "❤️"}`
- **THEN** the desktop overlay animates the emoji on screen

#### Scenario: Overlay not running — no crash
- **WHEN** daemon sends an emoji reaction but the desktop overlay is not running
- **THEN** the bridge logs a warning and continues without crashing

---

### Requirement: Bridge pushes slide_changed on PowerPoint navigation
The bridge SHALL poll PowerPoint via `ppt_probe.py` and send a `slide_changed` message to connected daemon clients whenever the current slide or deck changes.

#### Scenario: Slide navigation detected
- **WHEN** the presenter moves to a different slide in PowerPoint
- **THEN** the bridge sends `{"type": "slide_changed", "deck": "<deck name>", "slide": <slide_number>}` to the daemon within 3 seconds

#### Scenario: PowerPoint not running
- **WHEN** PowerPoint is not open
- **THEN** the bridge sends `{"type": "slide_changed", "deck": null, "slide": null}` once (on transition from running to not running), then suppresses further identical messages

---

### Requirement: Daemon WS client connects to bridge with reconnect
The training-assistant daemon SHALL include an `addon_bridge_client` that connects to `ws://localhost:56789/ws` on startup and reconnects automatically after any disconnect.

#### Scenario: Successful connection
- **WHEN** the daemon starts and the bridge is running
- **THEN** the client connects within 5 seconds and is ready to send/receive messages

#### Scenario: Bridge not running at startup — graceful retry
- **WHEN** the daemon starts but the bridge is not yet running
- **THEN** the client retries with exponential back-off (max 30 s interval) until the bridge becomes available; no error is shown to participants

#### Scenario: Connection lost mid-session
- **WHEN** the bridge crashes or is restarted
- **THEN** the daemon client detects the disconnect and reconnects automatically

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
