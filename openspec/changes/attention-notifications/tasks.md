# Phase 1 — Core (host enable-gate + host notification broadcast + participant→host bell)

## 1. De-risk the background-tab audio path FIRST (⚠️ primary risk)

- [x] 1.1 Prototype participant background-tab notification + sound: with permission granted, verify `new Notification(text)` surfaces (and makes its OS sound) while the session tab is backgrounded, on the target browsers (Chrome + Safari).
- [x] 1.2 Prototype the `<audio>` unlock during a user-gesture click (play+pause a muted clip), then attempt `play()` from a WS-message handler on a backgrounded tab; record which sound path is reliable.
- [x] 1.3 Decide the primary sound mechanism from the prototype (Notification-own-sound vs unlocked `<audio>`) and record it against design Open Question #1 before building the rest of Direction A.

## 2. Master enable-gate — `attention_enabled`, default OFF (do before wiring the bell/permission UI)

- [x] 2.1 Add `self.attention_enabled: bool = False` to `ParticipantState.__init__` (`daemon/participant/state.py`), next to `emoji_global_enabled` (`:47`) — **default OFF**.
- [x] 2.2 Carry it through `sync_from_restore` (mirror `:129-130`, keyed `"attention_enabled"`) and `snapshot()` (mirror `:146`).
- [x] 2.3 Reset it OFF in `ParticipantState.reset()` (mirror `:164`, but `= False`); confirm `reset()` runs on the fresh-session path (`daemon/__main__.py:1228`, `_participant_state.reset(...)`), so every session starts disabled.
- [x] 2.4 Add `attention_enabled: bool = False` to `HostStateResponse` (`daemon/host_state_router.py:90`) and surface it in the host state message (`:276`).
- [x] 2.5 Add the host toggle endpoint `POST /api/{session_id}/host/attention/global-toggle` returning `AttentionGlobalStateResponse{attention_enabled: bool}` (mirror the emoji toggle `daemon/emoji/router.py:106-122`): flip the flag, persist via `save_session_state`, and log it.
- [x] 2.6 Add `AttentionEnabledMsg{type:"attention_enabled", enabled:bool}` (Pydantic) to `daemon/ws_messages.py` and register it in `PARTICIPANT_MESSAGES` (`:323`); from the toggle endpoint, `broadcast(AttentionEnabledMsg(enabled=...))` so participants update live.
- [x] 2.7 Add `"attention_enabled": ps.attention_enabled` to the participant state payload in `get_participant_state` (`daemon/participant/router.py:714-770`) so joining/reconnecting participants render the correct surface.
- [x] 2.8 Host UI toggle: add `#attention-master-badge` (🔔) with `onclick="toggleAttentionGlobal()"` to the host footer (`static/host.html`, mirror `#emoji-master-badge` `:342`); add `applyAttentionMasterBadge(enabled)` + `toggleAttentionGlobal()` (`static/host.js`, mirror `:398`, `:791-808`) that POST the toggle endpoint and reflect the returned state.
- [x] 2.9 Participant live handler: add `case 'attention_enabled':` in `_handleWsMessage` (`static/participant.html:3914`) — when `enabled` → render the bell button into `#emoji-main-bar` and show the pinned permission indicator; when disabled → remove the bell button and hide/deactivate the indicator. No reload.

## 3. Direction A — daemon: host_notification message + endpoint

- [x] 3.1 Add `HostNotificationMsg{type:"host_notification", text:str, at:str}` (Pydantic) to `daemon/ws_messages.py` and register it in `PARTICIPANT_MESSAGES`.
- [x] 3.2 Add a host notification endpoint (mounted alongside the other host routers in `daemon/host_server.py`) that validates non-empty text and calls `broadcast(HostNotificationMsg(text=..., at=<iso now>))` (`daemon/ws_publish.py`).
- [x] 3.3 **Enforce the gate:** the host notification endpoint SHALL refuse (no broadcast) when `participant_state.attention_enabled` is off.

## 4. Direction A — participant page: pinned permission indicator (`static/participant.html`)

- [x] 4.1 Add a fixed, always-visible permission indicator (mirror `#reconnect-giveup` fixed CSS `:624`, or append into the `#floating-reactions` stack `:967`) reflecting granted / not-granted / denied.
- [x] 4.2 Wire its click handler to call `Notification.requestPermission()` **only on the click** (never on load) and update the indicator from the result; explain the denied state (re-enable in browser settings).
- [x] 4.3 In that same click gesture, unlock an `<audio>` element (play then pause) so later notification sounds can play from a backgrounded tab.
- [x] 4.4 **Gate it:** the indicator is hidden/inactive and never prompts for permission unless `attention_enabled` is on (driven by the `attention_enabled` broadcast + the initial state snapshot).

## 5. Direction A — participant page: host_notification receipt (`static/participant.html`)

- [x] 5.1 Add `case 'host_notification':` in `_handleWsMessage` (`:3914`): if permission granted → `new Notification(msg.text)` + play sound.
- [x] 5.2 Fallback when not granted → in-page toast (reuse `showToast()` `:2015`) + best-effort sound + pulse the pinned indicator to nudge enabling.

## 6. Direction A — host page control (`static/host.html` / `static/host.js`)

- [x] 6.1 Add a text input + "Send" button that POSTs to the host notification endpoint; disable the button on empty/whitespace-only input (per the project's disabled-button rule).
- [ ] 6.2 Optionally offer a default message (e.g. "We're resuming — please come back 🙌"); confirm presets vs free-text at approval (design Open Question #3).

## 7. Direction B — participant bell button + ringBell (`static/participant.html`)

- [x] 7.1 Add a bell button into `#emoji-main-bar` (`:968`), styled like the reaction buttons — rendered only while `attention_enabled` is on.
- [x] 7.2 Add `ringBell()` mirroring `sendEmoji` (`:1980`): `POST /{sessionId}/api/participant/bell` with header `X-Participant-ID` and no body.
- [x] 7.3 Add a light client-side throttle (mirror the emoji debounce + `429` "slow down" hint at `:1989`).

## 8. Direction B — daemon bell router (`daemon/bell/router.py`)

- [x] 8.1 Create `daemon/bell/router.py` with `participant_router = APIRouter(prefix="/api/participant/bell")` and a `POST` handler (`status_code=204`) mirroring `daemon/emoji/router.py`.
- [x] 8.2 **Enforce the gate first:** if `not participant_state.attention_enabled`, reject/ignore the ring (do not resolve, log, forward, or notify) — mirror the emoji short-circuit `daemon/emoji/router.py:70-71`, so a direct `POST` does nothing while disabled.
- [x] 8.3 Read `pid = request.headers.get("x-participant-id")` (400 if missing); resolve `caller = participant_state.participant_names.get(pid, pid)`.
- [x] 8.4 Log who + when: `daemon_log.info("addons   ", f"🔔 {caller!r} rang the bell")` (timestamp auto-prefixed by `daemon/log.py`), mirroring the emoji logging idiom (`daemon/emoji/router.py:84-91`).
- [x] 8.5 Add a server-side rate limit reusing `SlidingWindowRateLimiter` (keyed by pid) → `429` on excess; confirm the limit at approval (design Open Question #4).
- [x] 8.6 Mount the router in `daemon/host_server.py` next to `emoji_participant_router` (~ the `app.include_router(emoji_participant_router)` block).

## 9. Direction B — addons bridge sender + protocol doc

- [x] 9.1 Add `send_bell(caller_name)` to `AddonBridgeClient` (`daemon/addon_bridge_client.py`) next to `send_emoji` — emits `{"type":"bell_ring","caller":caller_name}` via `self._send(...)`, best-effort, never raises; log a drop when disconnected (mirror the emoji "bridge unavailable" branch).
- [x] 9.2 Add the module-level `send_bell(...)` wrapper (next to the `send_emoji` wrapper) and call it from the bell router.
- [x] 9.3 Document the `bell_ring` message in `docs/addons-ws.yaml` under the `subscribe` (daemon → addons) direction, alongside `display_emoji` (type + `caller` field).

## 10. Direction B — optional host-page render (dual-render, mirror emoji)

- [x] 10.1 (Optional) Add `BellRungMsg{type:"bell_rung", caller:str}` to the host message set and `await notify_host(BellRungMsg(caller=caller))` from the bell router so the host browser can render an incoming bell; confirm at approval (design Open Question #2).

## 11. Docs & API reference

- [x] 11.1 Regenerate `docs/openapi.yaml` (new `/api/participant/bell`, host notification endpoint, and `POST /api/{session_id}/host/attention/global-toggle`) and any touched WS YAMLs.
- [x] 11.2 Regenerate `API.md` via `python3 scripts/generate_apis_md.py --output API.md` (never hand-edit `API.md`); record the change in `backlog.md`.

## 12. Tests

- [x] 12.1 Daemon test: the master gate defaults OFF on a fresh `ParticipantState` and after `reset()`; the toggle endpoint flips it, persists it, and `broadcast()`s an `attention_enabled` message; the flag appears in the host state and the participant state snapshot.
- [x] 12.2 Daemon test (defense in depth): with the gate OFF, `POST /api/participant/bell` is rejected/ignored (no `send_bell`, no host notify) and the host-notification endpoint refuses to broadcast; with the gate ON both proceed.
- [x] 12.3 Daemon test: `POST /api/participant/bell` with a known `X-Participant-ID` (gate ON) resolves the name, logs it, calls `send_bell`, and returns 204; missing header → 400; excess rings → 429.
- [x] 12.4 Daemon test: bell forward degrades gracefully when the bridge is disconnected (logs, still 204).
- [x] 12.5 Daemon test: the host notification endpoint broadcasts a `host_notification` with the text + timestamp to all participants; empty text is rejected.
- [x] 12.6 Hermetic E2E: toggling the host `#attention-master-badge` makes the bell button + permission indicator appear/disappear live on a connected participant (no reload); a `host_notification` reaches a participant client and takes the granted (Notification) vs not-granted (toast) branch correctly; mark slow tests `@pytest.mark.nightly`.
- [x] 12.7 Run `bash tests/run-daemon-tests.sh` and `bash tests/docker/run-hermetic.sh`; capture evidence.

---

# Later stage — NOT part of phase-1 delivery

## 13. Individual-participant targeting (deferred)

- [ ] 13.1 Add a participant picker on the host page and per-UUID routing so a host notification can target a single participant (or subset) instead of broadcasting to all.

## 14. Tab-closed delivery via web-push (deferred, explicit non-goal for now)

- [ ] 14.1 Evaluate web-push + a service worker so host notifications reach a participant whose session tab is fully closed (a much larger lift than the backgrounded-tab path this change delivers).
