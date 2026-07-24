## Context

The tool runs as two processes: the public Railway gateway (`railway/`) serves pages and proxies API calls, and a local **daemon** (`daemon/`) owns interaction logic. There are two live transports already in place, and this change adds features to both without touching either transport's core:

1. **Railway relay (daemon → participants).** `broadcast(msg)` (`daemon/ws_publish.py:55`) wraps a typed Pydantic model in the generic `{"type":"broadcast","event":{…}}` envelope that Railway forwards to participant browsers without knowing the event type. Participant message types are registered in `PARTICIPANT_MESSAGES` (`daemon/ws_messages.py:323`) and handled client-side in `_handleWsMessage` (`static/participant.html:3914`). `notify_host(msg)` (`daemon/ws_publish.py:72`) pushes to host browser WS. **New participant message types need no `railway/**` change** — they ride the existing envelope.
2. **Addons bridge (daemon → overlay).** `AddonBridgeClient` (`daemon/addon_bridge_client.py`) is a persistent WS client to the macOS overlay's local server at `ws://127.0.0.1:8765`; `send_emoji(emoji, glow)` (:60) emits `{"type":"display_emoji",…}` best-effort (never raises). New daemon→overlay messages are added as new `send_*` methods here and documented in `docs/addons-ws.yaml`.

Participant API is proxied Railway → daemon (catch-all `railway/features/ws/proxy_bridge.py`) and keyed off the `X-Participant-ID` header. The emoji feature is the canonical precedent for everything here: `daemon/emoji/router.py` exposes `POST /api/participant/emoji/reaction`, resolves the sender name via `participant_state.participant_names.get(pid, …)`, logs with `daemon_log.info("addons   ", …)` (the `addons` channel is the daemon→overlay direction; the timestamp is auto-prefixed by `daemon/log.py`), forwards to the overlay via `addon_bridge_client.send_emoji(...)`, and also `notify_host(...)` so the host browser renders it too — a **dual-render** design (overlay + host page). This change mirrors that precedent for the bell.

The frontend is vanilla HTML + inline JS (Tailwind, no bundler). Participant reactions live in `#floating-reactions` → `#emoji-main-bar` (`static/participant.html:967-968`); buttons are injected by `renderEmojiBar()` (:2248) and each calls `sendEmoji(emoji, btn)` (:1980), which fires the local float animation, POSTs to the emoji endpoint with `X-Participant-ID: _myUUID`, and shows a "Slow down 🐢" toast on `429`. The fixed reconnect banner `#reconnect-giveup` (:624) is the CSS precedent for a pinned always-visible bar.

**Confirmed product decisions** (from the user), stated here so implementers do not re-litigate them:
- The whole capability — **both** directions — is **off by default** and must be **explicitly enabled by the host from the host web UI**. It resets to off at every session start. Only when the host enables it do participants get the bell in their reaction bar and the notification-permission affordance. This mirrors the existing `emoji_global_enabled` host-toggle pattern (Decision 6).
- The bell card shows the caller's **real name**, which depends on the `participant-real-names` change. Until real names exist it shows whatever name the participant currently has (fictional/assigned).
- Participants keep the session tab **open** (backgrounded) during breakouts → a normal page `Notification` suffices; **no web-push / service worker** (an explicit non-goal; the future option if tab-closed delivery is ever needed).
- Host notifications broadcast to **all** participants; individual targeting is a later stage.
- No-permission fallback = an in-tab toast **and** a sound, and the pinned indicator nudges the participant to enable notifications.

## Goals / Non-Goals

**Goals:**
- A host-controlled master enable-gate that turns the whole capability (both directions) on/off from the host UI, defaulting OFF and resetting OFF every session, broadcast live to participants and enforced daemon-side.
- Host → all participants: an OS notification with sound that surfaces on a backgrounded tab, with a graceful in-page fallback when permission is absent.
- A pinned, always-visible participant control that reflects notification-permission state and requests permission only on a user gesture.
- Participant → host: a bell that logs who + when on the daemon and forwards `bell_ring` to the overlay via the existing 8765 bridge.
- Reuse the emoji precedent end-to-end (button wiring, name resolution, `addons` logging idiom, dual-render, bridge sender, throttle) — minimal new surface.
- Ship with **no Railway redeploy** (message types + `/api/participant/*` endpoints only).

**Non-Goals:**
- No web-push, no service worker, no tab-closed delivery.
- No individual-participant targeting of host notifications (broadcast-only in phase 1).
- No structured event log / DB for bell events (daemon log only, per emoji precedent).
- No changes to `railway/app.py`, `railway/features/ws/router.py`, or the relay/proxy core.

## Decisions

### 1. Direction A delivery: typed participant broadcast, dual receipt path
Add `HostNotificationMsg{type:"host_notification", text:str, at:str}` to `daemon/ws_messages.py` and register it in `PARTICIPANT_MESSAGES`. A new **host** endpoint (mounted alongside the other host routers) validates the text and calls `broadcast(HostNotificationMsg(text=..., at=now_iso()))`. Client-side, `_handleWsMessage` gains `case 'host_notification':`:
- If `Notification.permission === 'granted'`: `new Notification(msg.text)` **and** play the notification sound.
- Else: show an in-page toast (reuse the `showToast()` pattern, `participant.html:2015`) **and** play the sound, and make the pinned indicator pulse to nudge enabling.

`at` is an ISO timestamp for display/debug parity with other messages; the notification body is `text`.

**Alternatives considered:** a host-only daemon-localhost endpoint vs a Railway-proxied one — the notification broadcast is triggered by the host page (which talks to the daemon through the same host WS/HTTP path as other host controls), so this follows the existing host-endpoint pattern (e.g. the emoji global toggle `host_router` at `/api/{session_id}/host/emoji`). Individual targeting was rejected for phase 1 (needs a participant picker + per-UUID routing).

### 2. Direction A permission: pinned indicator, gesture-only request, audio unlock
A fixed, always-visible bottom element (mirroring `#reconnect-giveup`'s fixed CSS, or appended into the `#floating-reactions` stack) shows the current `Notification.permission` state (granted / not-granted / denied). **Requesting permission happens only inside the click handler** — never on page load — because browsers require a user gesture and an on-load prompt is both hostile and often auto-denied. During that same click gesture, also **unlock a short muted `<audio>` element** (play + immediately pause) so the browser's autoplay policy lets us play sound later, including from a backgrounded tab (see Risk 1). When permission is `denied`, the indicator explains it must be re-enabled in browser settings (a second `requestPermission()` is a no-op once denied).

### 3. Direction B participant button: mirror `sendEmoji`
Add a bell button into `#emoji-main-bar` (`participant.html:968`), styled like the reaction buttons, wired to a new `ringBell()` that mirrors `sendEmoji` (:1980): fire an optional local affordance, then `POST /{sessionId}/api/participant/bell` with `headers:{ 'X-Participant-ID': _myUUID }` and **no body** (the daemon resolves the name from the UUID). Apply a light client-side throttle mirroring the emoji path (debounce + a "Slow down 🐢"-style hint on `429`), so a participant cannot machine-gun the host's overlay.

### 4. Direction B daemon router: resolve, log, forward (mirror emoji router)
New `daemon/bell/router.py` with `participant_router = APIRouter(prefix="/api/participant/bell")`, mounted in `daemon/host_server.py` next to `emoji_participant_router`. The `POST` handler (`status_code=204`, like emoji):
1. reads `pid = request.headers.get("x-participant-id")` (400 if missing);
2. resolves `caller = participant_state.participant_names.get(pid, pid)`;
3. **logs who + when**: `daemon_log.info("addons   ", f"🔔 {caller!r} rang the bell")` (timestamp auto-prefixed by `daemon/log.py`; `addons` is the daemon→overlay channel);
4. forwards to the overlay: `addon_bridge_client.send_bell(caller)` — best-effort, logs a drop when the bridge is disconnected (mirroring the emoji "bridge unavailable" branch);
5. optionally `await notify_host(BellRungMsg(caller=caller))` so the host browser page can render it too (dual-render, mirroring emoji). A light server-side rate-limit (reuse `SlidingWindowRateLimiter` like emoji, keyed by pid) protects the host from spam and returns `429`.

`send_bell(caller_name)` is a new method on `AddonBridgeClient` next to `send_emoji`, plus a module-level wrapper: `msg = {"type":"bell_ring","caller":caller_name}; return self._send(msg)` — best-effort, never raises.

**Alternatives considered:** forwarding only to the overlay (no host render) — kept as the default with host render optional, matching emoji's dual-render; a raw dict endpoint — rejected per the project's Pydantic-contracts rule.

### 5. Shared `bell_ring` contract (documented identically in both repos)
This is the single wire contract linking `training-assistant` and `victor-macos-addons`. It is written verbatim below and in the `bell-overlay-card` design in the addons repo.

```
Message:    bell_ring
Transport:  ws://127.0.0.1:8765   (the addons-owned local WebSocket server;
            the daemon connects as a client via AddonBridgeClient)
Direction:  daemon → overlay      (in docs/addons-ws.yaml terms: a `subscribe`
            message — one the daemon sends TO addons)
Payload:
    {
      "type":   "bell_ring",
      "caller": "<participant display name>"
    }
Fields:
  - type   (string, required): the literal "bell_ring"
  - caller (string, required): the ringing participant's resolved display name.
           Real name once `participant-real-names` lands; otherwise the current
           fictional/assigned name. Never the raw UUID when a name is known.
Semantics:  Fire-and-forget, best-effort. If the overlay is not connected the
            daemon logs the drop and returns success to the participant (no
            error surfaces). On receipt the overlay plays a bell sound and shows
            a PERSISTENT, hover-dismissible bottom-left card reading exactly
            "🔔 [caller] is calling you" (caller name substituted). Multiple
            bells may stack. There is no auto-fade timer — the card stays until
            the host hovers it away.
```

The addons `docs/addons-ws.yaml` in this repo gains a matching `bell_ring` entry under the `subscribe` (daemon → addons) side, alongside `display_emoji`.

### 6. Master enable-gate: host-controlled `attention_enabled`, default OFF, broadcast + enforced
The whole capability (both directions) is gated behind one session-wide flag, `attention_enabled`, modelled directly on the existing `emoji_global_enabled` master switch — with two deliberate differences: it **defaults OFF** and it is **broadcast to participants** (the emoji switch is host-only).

**Exact `emoji_global_enabled` symbols to mirror** (so the implementer follows the same pattern):

| Concern | Existing `emoji_global_enabled` (mirror this) | New `attention_enabled` |
| --- | --- | --- |
| State field | `daemon/participant/state.py:47` — `self.emoji_global_enabled: bool = True` | add `self.attention_enabled: bool = False` next to it — **default OFF** |
| Restore | `daemon/participant/state.py:129-130` — `if isinstance(data.get("emoji_global_enabled"), bool): self.emoji_global_enabled = data[...]` | same, keyed `"attention_enabled"` |
| Snapshot | `daemon/participant/state.py:146` — `"emoji_global_enabled": self.emoji_global_enabled` | add `"attention_enabled": self.attention_enabled` |
| Session reset | `daemon/participant/state.py:164` — `self.emoji_global_enabled = True` (inside `reset()`) | `self.attention_enabled = False` — **reset OFF**; `reset()` is called from the fresh-session path `daemon/__main__.py:1228` (`_participant_state.reset(...)`) |
| Daemon enforcement | `daemon/emoji/router.py:70-71` — `if not participant_state.emoji_global_enabled: return Response(status_code=204)` | bell endpoint short-circuits (reject/ignore) when off; host-notification endpoint refuses when off |
| Host toggle endpoint | `daemon/emoji/router.py:106-122` — `host_router = APIRouter(prefix="/api/{session_id}/host/emoji")`, `POST /global-toggle` flips + persists, returns `EmojiGlobalStateResponse` | `POST /api/{session_id}/host/attention/global-toggle` flips + persists + **`broadcast(AttentionEnabledMsg(enabled=...))`**, returns `AttentionGlobalStateResponse{attention_enabled}` |
| Host state field | `daemon/host_state_router.py:90` — `emoji_global_enabled: bool = True` on `HostStateResponse`; surfaced at `:276` | add `attention_enabled: bool = False` + surface it |
| Host badge (HTML) | `static/host.html:342` — `<span id="emoji-master-badge" ... onclick="toggleEmojiGlobal()">❤️</span>` | `<span id="attention-master-badge" ... onclick="toggleAttentionGlobal()">🔔</span>` |
| Host badge (JS) | `static/host.js:398` `applyEmojiMasterBadge(msg.emoji_global_enabled !== false)`; `:791-798` `applyEmojiMasterBadge(enabled)`; `:800-808` `toggleEmojiGlobal()` → `POST /emoji/global-toggle` | `applyAttentionMasterBadge(msg.attention_enabled === true)`; `toggleAttentionGlobal()` → `POST /attention/global-toggle` |

**What is net-new relative to the emoji switch (the participant-facing half):**
- **Live broadcast.** The toggle endpoint additionally `broadcast()`s a new participant message `AttentionEnabledMsg{type:"attention_enabled", enabled:bool}` (added to `daemon/ws_messages.py` and registered in `PARTICIPANT_MESSAGES` at `daemon/ws_messages.py:323`). Client-side, `_handleWsMessage` (`static/participant.html:3914`) gains `case 'attention_enabled':` — when `enabled` is true it renders the bell button into `#emoji-main-bar` and shows the pinned permission indicator; when false it removes the bell button and hides/deactivates the indicator. No reload.
- **Initial state on join/reconnect.** The flag also rides the participant state snapshot built in `get_participant_state` (`daemon/participant/router.py:714-770`, add `"attention_enabled": ps.attention_enabled`), which the page fetches on load and on WS reconnect (`_refreshParticipantState`, `static/participant.html:3317`). So a participant who joins while the feature is already on renders the bell immediately, and one who joins while off does not.

**Defense in depth (not just UI hiding).** UI hiding is a convenience, not the boundary. The daemon independently enforces the gate:
- The bell endpoint (`daemon/bell/router.py`) checks `participant_state.attention_enabled` first and rejects/ignores the ring when off (mirroring the emoji router's `if not participant_state.emoji_global_enabled:` short-circuit at `daemon/emoji/router.py:70`), so a hand-crafted `POST /api/participant/bell` does nothing.
- The host-notification broadcast endpoint refuses to `broadcast(HostNotificationMsg(...))` when off.

**Permission affordance is gated too.** The pinned indicator only presents/activates its `Notification.requestPermission()` affordance when `attention_enabled` is on — there is no point prompting for OS-notification permission the host never uses.

**Swift overlay unaffected.** The overlay side (`victor-macos-addons`, `bell-overlay-card`, already merged) needs no change for this gate: when the feature is disabled the daemon never sends `bell_ring`, so the overlay is inherently inert. No one should re-touch the addons repo for this.

**Alternatives considered:** defaulting ON like the emoji switch — rejected because the product requirement is explicit opt-in per session (the host decides when the audience may ring / be notified). A host-only flag with no participant broadcast (exact emoji parity) — rejected because participants must see the bell appear/disappear the instant the host toggles, without reloading.

## Risks / Trade-offs

### ⚠️ RISK 1 (primary, design-level) — Browsers throttle/block audio in backgrounded tabs
Direction A's entire value is reaching a participant whose tab is **backgrounded**. But browsers aggressively throttle/block `Audio()` / `HTMLAudioElement.play()` in backgrounded, non-focused tabs and gate autoplay behind a prior user gesture. A naive `new Audio(url).play()` fired from a WS message on a backgrounded tab may silently do nothing. Two reliable paths, and one mitigation:
- **Preferred:** rely on the **Notification API's own sound** — a `new Notification(text)` shown by the browser/OS makes its own notification sound at the OS level, independent of tab focus. This is the most reliable "sound reaches a distracted user" path.
- **Secondary:** **unlock an `<audio>` element during the permission-grant user gesture** (Decision 2) — play+pause a muted clip on the click so the element is "blessed", then later `play()` it from the WS handler. Unlocked media elements are far more likely to play while backgrounded than a fresh `Audio()`.
- **Mitigation:** when neither Notification nor unlocked-audio fires (permission absent / autoplay still blocked), the in-page toast + best-effort sound still shows the moment the participant returns to the tab.

**This risk MUST be de-risked first:** "prototype participant background-tab notification + sound" is one of the earliest phase-1 tasks (see tasks.md §1). If the reliable path turns out to be Notification-sound-only, the `<audio>` unlock becomes belt-and-suspenders rather than the primary mechanism.

### Other risks
- **Overlay stronger than participant direction.** Direction B reaches the host even with the browser backgrounded / fullscreen PowerPoint because the overlay is a separate always-running native app — a stronger delivery guarantee than Direction A. This asymmetry is expected, not a defect.
- **Bell spam → host distraction.** Mitigated by client throttle (Decision 3) + server rate-limit (Decision 4), reusing the emoji rate-limit primitive.
- **Name is not yet real** (pre `participant-real-names`) → the card shows the current fictional name; acceptable and self-correcting once real names ship.
- **Permission denied is sticky** → the pinned indicator must clearly explain re-enabling in browser settings; a repeat `requestPermission()` is a silent no-op once denied.
- **Bridge disconnected when a bell arrives** → `send_bell` returns `False`; the daemon logs the drop (like emoji) and still returns 204 to the participant — the ring is best-effort, never an error.

## Migration Plan

- **Additive only.** New message types (`AttentionEnabledMsg`, `HostNotificationMsg`, optional `BellRungMsg`), a new `attention_enabled` flag on `ParticipantState` (default OFF), a new host toggle endpoint `POST /api/{session_id}/host/attention/global-toggle`, a new `/api/participant/bell` endpoint, a new host notification endpoint, a new `send_bell` bridge method, a new `bell_ring` entry in `docs/addons-ws.yaml`. No existing contract changes; `attention_enabled` is a new persisted state field that defaults OFF, so existing sessions restore to OFF (safe default).
- **No Railway redeploy.** Participant messages ride the `broadcast` envelope; `/api/participant/*` rides the catch-all proxy; `static/` + `daemon/` hot-deploy on push to `master` (daemon `static_sync` + in-process reload).
- **Docs.** Regenerate `docs/openapi.yaml` and any WS YAMLs, then `API.md` via `python3 scripts/generate_apis_md.py --output API.md` (never hand-edit `API.md`). Record in `backlog.md`.
- **Cross-repo coordination.** The overlay must handle `bell_ring` (change `bell-overlay-card` in `victor-macos-addons`). Until it does, `send_bell` is a harmless no-op on the wire (the overlay logs & ignores unknown types). Ship order is independent; the daemon side degrades gracefully.
- **Rollback.** Revert the change dir + remove the new routers/message/sender + the `docs/addons-ws.yaml` entry. No persisted state to unwind.

## Open Questions

1. **[RESOLVED] Notification sound source.** Settled in phase-1 implementation: the **primary** path is the **Notification API's own OS sound** — a `new Notification(text)` surfaces and chimes at the OS level even on a backgrounded tab, independent of the tab's autoplay throttling. The **secondary** path is an unlocked `<audio>` element (a short chime embedded as a data URI, `play()`+`pause()` inside the permission-grant click gesture) — it powers the sound for the **no-permission toast fallback** and is belt-and-suspenders alongside the Notification chime. No web-push/service worker. (Original flag: confirm primary=Notification-own-sound with `<audio>` secondary — confirmed.)
2. **[FLAG] Host render of the bell.** Confirm whether the host **browser page** should also render an incoming bell (dual-render, mirroring emoji) or whether the overlay card alone is sufficient. Default: include the optional `notify_host(...)` + host-page affordance.
3. **[FLAG] Notification copy & controls.** Confirm the host notification input is free-text (with a sensible default like "We're resuming — please come back 🙌") and whether a short list of quick presets ("Resuming", "5 min break", "Q&A now") is wanted in phase 1 or later.
4. **[FLAG] Bell throttle limits.** Confirm the per-participant bell rate (proposed: reuse the emoji limiter's window; e.g. a few rings/minute) and the client debounce interval.
5. **[FLAG] Pinned indicator placement.** Confirm the pinned permission indicator as a fixed bottom bar (like `#reconnect-giveup`) vs an item appended into the `#floating-reactions` stack, and its copy when granted / not-granted / denied.
