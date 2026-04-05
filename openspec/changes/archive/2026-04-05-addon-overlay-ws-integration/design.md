## Context

The training-assistant daemon runs on the trainer's Mac alongside `victor-macos-addons`. Two integrations with addons are currently broken or inefficient:

1. **Emoji reactions** — `daemon/emoji/router.py` attempts `POST http://localhost:8765/emoji` on every participant reaction, but no HTTP server exists at that port in addons. The call silently fails every time.
2. **Current slide tracking** — `daemon/__main__.py` polls `activity-slides-YYYY-MM-DD.md` every 0.5 s inside the main async loop to detect PowerPoint navigation. This couples the daemon to a file-path convention and adds 0–500 ms latency to slide updates broadcast to participants.

The `victor-macos-addons` repo already has all the pieces: a WS server at port 8765 (`wispr-flow/ws_server.py`) that knows the current slide and can relay emoji animations to the overlay. What's missing is the daemon connecting to this existing server.

## Goals / Non-Goals

**Goals:**
- Establish a persistent WS connection: daemon (client) ↔ addons WS server (already running at `ws://127.0.0.1:8765`)
- Fix emoji forwarding: daemon sends `emoji` message over WS; addons server relays animation to overlay
- Replace file-polling: addons server pushes `slide` on every PPT navigation; daemon updates `slides_current` state immediately
- Document the protocol in `apis.md`

**Non-Goals:**
- Replacing the existing Railway/daemon WS (that's a separate channel for participants and host)
- Changing participant-facing behaviour (slide display, emoji display)
- Moving audio/transcription logic
- Any remote/cloud connectivity — this is strictly localhost IPC

## Decisions

### WS over HTTP REST
The original HTTP POST approach requires the addons side to run an HTTP server. A persistent WS connection is superior: it's bidirectional (needed for slide push), has lower per-message overhead, and a single reconnect loop handles all message types. The addons WS server at port 8765 is already implemented and running.

*Alternative considered*: Named pipes / Unix domain sockets — simpler but non-standard for Python asyncio and harder to test.

### Addons is the server, daemon is the client
The daemon already manages reconnect logic for its Railway WS client. Reusing the same pattern (daemon retries on disconnect) keeps the addons server stateless — it doesn't need to know whether the daemon is connected. Overlay animations still work even when the daemon is offline.

*Alternative considered*: Daemon as server, addons as client — would require addons to know the daemon's port, and the daemon would have to handle overlay clients mixed with the main WS logic.

### Addons WS server is already provided (`wispr-flow/ws_server.py`, port 8765)
The server runs on `ws://127.0.0.1:8765`. On connect, it immediately sends the last known slide state as a welcome message. Protocol:
- On `emoji` message from daemon → relays animation to the overlay
- On slide change → sends `slide` message to all connected clients

No changes needed to addons.

### Daemon side: new `addon_bridge_client.py`
Small async WS client (similar to `materials/ws_runner.py`). Injected into `__main__.py` startup. Replaces:
- `httpx.AsyncClient().post("http://localhost:8765/emoji", ...)` in `emoji/router.py`
- The file-read loop for `activity-slides-*` in `__main__.py`

### Port 8765
The addons WS server listens on port 8765 (configurable via `WS_SERVER_PORT` env var). Document it explicitly in `apis.md`.

## Risks / Trade-offs

- **Overlay animation delivery** — the addons WS server handles emoji-to-overlay forwarding internally; no extra work needed in the daemon.
- **Race on startup** — daemon may try to connect before the addons WS server is ready. → Mitigation: daemon retries with exponential back-off (same pattern as Railway WS client).
- **File-poll removal** — removing the 0.5 s loop simplifies the daemon but means slides only update when the addons server is running. → Mitigation: daemon falls back gracefully (keeps last known `slides_current`) when disconnected; no crash.
- **Single repo change** — only `training-assistant` needs code changes. Addons already provides the WS server at port 8765.

## Migration Plan

1. Merge daemon changes into `training-assistant` and push to `master` (daemon auto-restarts).
2. Ensure addons is running on trainer's Mac (WS server at port 8765 starts automatically).
3. Verify: send a test emoji → overlay animates; navigate a slide → participant page updates < 1 s.

Rollback: revert daemon commit on `master`; daemon auto-restarts with old file-poll logic.
