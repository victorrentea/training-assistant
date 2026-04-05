## Context

The training-assistant daemon runs on the trainer's Mac alongside `victor-macos-addons`. Two integrations with addons are currently broken or inefficient:

1. **Emoji reactions** — `daemon/emoji/router.py` attempts `POST http://localhost:56789/emoji` on every participant reaction, but no HTTP server exists at that port in addons. The call silently fails every time.
2. **Current slide tracking** — `daemon/__main__.py` polls `activity-slides-YYYY-MM-DD.md` every 0.5 s inside the main async loop to detect PowerPoint navigation. This couples the daemon to a file-path convention and adds 0–500 ms latency to slide updates broadcast to participants.

The `victor-macos-addons` repo already has all the pieces to know the current slide (via `powerpoint-monitor/ppt_probe.py`) and to animate reactions on screen (via `desktop-overlay`). What's missing is an active communication channel.

## Goals / Non-Goals

**Goals:**
- Establish a persistent WS connection: daemon (client) ↔ addons bridge (server) at `ws://localhost:56789/ws`
- Fix emoji forwarding: daemon sends `emoji_reaction` over WS; bridge triggers overlay animation
- Replace file-polling: addons bridge pushes `slide_changed` on every PPT navigation; daemon updates `slides_current` state immediately
- Document the protocol in `apis.md`

**Non-Goals:**
- Replacing the existing Railway/daemon WS (that's a separate channel for participants and host)
- Changing participant-facing behaviour (slide display, emoji display)
- Moving audio/transcription logic
- Any remote/cloud connectivity — this is strictly localhost IPC

## Decisions

### WS over HTTP REST
The original HTTP POST approach requires the addons side to run an HTTP server. A persistent WS connection is superior: it's bidirectional (needed for slide push), has lower per-message overhead, and a single reconnect loop handles all message types.

*Alternative considered*: Named pipes / Unix domain sockets — simpler but non-standard for Python asyncio and harder to test.

### Addons is the server, daemon is the client
The daemon already manages reconnect logic for its Railway WS client. Reusing the same pattern (daemon retries on disconnect) keeps the addons bridge stateless — it doesn't need to know whether the daemon is connected. Overlay animations still work even when the daemon is offline.

*Alternative considered*: Daemon as server, addons as client — would require addons to know the daemon's port, and the daemon would have to handle overlay clients mixed with the main WS logic.

### New `addon-bridge` module in addons (Python asyncio + `websockets`)
`wispr-flow/app.py` is a `rumps` app on the main thread; injecting a WS server there would complicate threading. A separate module (`addon-bridge/`) started independently (by `start.sh` or as a `wispr-flow` background thread) keeps concerns separate.

Bridge responsibilities:
- Run `asyncio` WS server on `localhost:56789`
- On `emoji_reaction` message from daemon → trigger overlay animation (HTTP POST to desktop-overlay or direct AppleScript/process signal)
- Poll PowerPoint every 3 s (reuse `ppt_probe.py`) → on change, send `slide_changed` to all connected daemon clients

### Daemon side: new `addon_bridge_client.py`
Small async WS client (similar to `materials/ws_runner.py`). Injected into `__main__.py` startup. Replaces:
- `httpx.AsyncClient().post("http://localhost:56789/emoji", ...)` in `emoji/router.py`
- The file-read loop for `activity-slides-*` in `__main__.py`

### Port 56789
Already used in `daemon/emoji/router.py` as the target port. Keep it for continuity; document it explicitly.

## Risks / Trade-offs

- **Overlay animation delivery** — bridge needs to trigger the overlay when it receives an emoji. The overlay currently connects to Railway WS (`/ws/__overlay__`); the bridge can call a local endpoint on the overlay or use a shared asyncio queue if co-located. → Mitigation: bridge sends an HTTP POST to the overlay's own local listener, or triggers via the existing Railway path if daemon is running.
- **Race on startup** — daemon may connect to bridge before bridge is fully ready. → Mitigation: daemon retries with exponential back-off (same pattern as Railway WS client).
- **File-poll removal** — removing the 0.5 s loop simplifies the daemon but means slides only update when bridge is running. → Mitigation: daemon falls back gracefully (keeps last known `slides_current`) when bridge disconnects; no crash.
- **Two repos** — changes span `training-assistant` and `victor-macos-addons`. Both must be deployed/restarted together. → Mitigation: document in `apis.md` and `start.sh`.

## Migration Plan

1. Merge `addon-bridge` into `victor-macos-addons` and update `start.sh` there to launch it.
2. Merge daemon changes into `training-assistant` and push to `master` (daemon auto-restarts).
3. Restart addons (`start.sh`) on trainer's Mac.
4. Verify: send a test emoji → overlay animates; navigate a slide → participant page updates < 1 s.

Rollback: revert daemon commit on `master`; daemon auto-restarts with old file-poll logic.
