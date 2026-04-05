## 1. addons: addon-bridge module (victor-macos-addons repo)

- [ ] 1.1 Create `addon-bridge/` directory with `__main__.py` entry point and `server.py`
- [ ] 1.2 Implement asyncio WS server on `localhost:56789` in `server.py` (accept connections, dispatch messages)
- [ ] 1.3 Handle `emoji_reaction` message: forward to desktop overlay (HTTP POST to overlay's local endpoint or trigger via existing channel)
- [ ] 1.4 Add PowerPoint polling loop (reuse `powerpoint-monitor/ppt_probe.py`); send `slide_changed` to connected clients on navigation change
- [ ] 1.5 Add graceful handling: PowerPoint not running → send `slide_changed` with null deck/slide once
- [ ] 1.6 Update `start.sh` in addons to launch `addon-bridge` in background alongside desktop-overlay

## 2. daemon: addon-bridge WS client (training-assistant repo)

- [ ] 2.1 Create `daemon/addon_bridge_client.py` — asyncio WS client that connects to `ws://localhost:56789/ws` with exponential back-off reconnect
- [ ] 2.2 Wire client into `daemon/__main__.py` startup (start as background task, inject into app state)
- [ ] 2.3 Handle `slide_changed` message in client: update `misc_state.slides_current` and broadcast `slides_current` WS event to all participants and host
- [ ] 2.4 Remove the `activity-slides-*.md` file-polling loop from `daemon/__main__.py`
- [ ] 2.5 Update `daemon/emoji/router.py`: replace `httpx` POST to `localhost:56789/emoji` with `addon_bridge_client.send({"type": "emoji_reaction", "emoji": emoji})` (best-effort, no raise on failure)
- [ ] 2.6 Track `overlay_connected: bool` in daemon state (set True on bridge connect, False on disconnect); include it in host WS state messages via `daemon/host_state_router.py`; push a host state update immediately on each connection-state change

## 3. Documentation

- [ ] 3.1 Add **Daemon ↔ Addons Bridge WS** section to `apis.md` with: port, message types (`emoji_reaction`, `slide_changed`), direction, and reconnect behaviour
- [ ] 3.2 Update `ARCHITECTURE.md` system interactions sequence diagram to include the Daemon ↔ Addons WS link

## 4. Tests

- [ ] 4.1 Add unit test for `addon_bridge_client`: mock WS server, verify `slide_changed` updates `misc_state.slides_current`
- [ ] 4.2 Update existing emoji router test (`tests/daemon/test_emoji_router.py`): replace HTTP mock with bridge client mock; verify best-effort (no error when bridge not connected)
