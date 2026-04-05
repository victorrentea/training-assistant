## 1. daemon: addon-bridge WS client (training-assistant repo)

- [ ] 1.1 Create `daemon/addon_bridge_client.py` — asyncio WS client that connects to `ws://127.0.0.1:8765` with exponential back-off reconnect
- [ ] 1.2 Wire client into `daemon/__main__.py` startup (start as background task, inject into app state)
- [ ] 1.3 Handle `slide` message in client: update `misc_state.slides_current` and broadcast `slides_current` WS event to all participants and host
- [ ] 1.4 Remove the `activity-slides-*.md` file-polling loop from `daemon/__main__.py`
- [ ] 1.5 Update `daemon/emoji/router.py`: replace `httpx` POST to `localhost:8765/emoji` with `addon_bridge_client.send({"type": "emoji", "emoji": emoji, "count": 1})` (best-effort, no raise on failure)
- [ ] 1.6 Track `overlay_connected: bool` in daemon state (set True on bridge connect, False on disconnect); include it in host WS state messages via `daemon/host_state_router.py`; push a host state update immediately on each connection-state change

## 2. Documentation

- [ ] 2.1 Add **Daemon ↔ Addons Bridge WS** section to `apis.md` with: port 8765, message types (`emoji`, `slide`), direction, welcome-on-connect behaviour, and reconnect behaviour
- [ ] 2.2 Update `ARCHITECTURE.md` system interactions sequence diagram to include the Daemon ↔ Addons WS link

## 3. Tests

- [ ] 3.1 Add unit test for `addon_bridge_client`: mock WS server, verify `slide` message updates `misc_state.slides_current`
- [ ] 3.2 Update existing emoji router test (`tests/daemon/test_emoji_router.py`): replace HTTP mock with bridge client mock; verify best-effort (no error when bridge not connected)
