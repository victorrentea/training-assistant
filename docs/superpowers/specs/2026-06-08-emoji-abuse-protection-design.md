# Emoji Master Switch — Design

**Date:** 2026-06-08
**Status:** Implemented

## Goal

Give the host one instant way to stop emoji-reaction abuse during a live session: a **global master switch** — a footer badge (❤️) next to the 👁 engagement eye. Green border = emojis enabled; click to disable (gray). When disabled, no participant emoji reaches the host screen or the macOS desktop overlay.

## Scope note — per-participant blocking dropped

The feature was originally scoped with a second control: a per-participant emoji counter that the host could click to block an individual spammer. During design exploration this was **dropped**, because it is not enforceable:

- A participant's UUID is their **only** credential — the `X-Participant-ID` header *is* their identity, and the daemon does **not** validate that the UUID belongs to a registered participant.
- UUIDs already leak broadly to participant browsers today (`ScoresUpdatedMsg` sends the full `{uuid: score}` map; Q&A sends `author_uuid` + `upvoter_uuids`; debate sends `author_uuid` + `upvoters`).

So a blocked spammer could simply send reactions under another participant's UUID, getting an innocent participant blocked instead. Per-participant blocking is therefore security theatre and was cut. The underlying UUID-leak / no-validation issue is recorded as a deferred, accepted risk in `backlog.md` — it is **out of scope** of this change.

## Decisions

| Question | Decision |
|---|---|
| Global OFF behavior | Drop silently server-side: the daemon early-returns `204` before forwarding or counting. The participant's local float animation still plays; they stay unaware. |
| Persistence | Persist `emoji_global_enabled` in `session-state.json` — survives daemon restart / session resume. Defaults to enabled. |
| Enforcement location | Entirely in the daemon emoji handler — the only place that also suppresses the desktop overlay. Railway stays a dumb proxy. |

## Architecture

### 1. Daemon state — `daemon/participant/state.py`
One new field on the `ParticipantState` singleton: `emoji_global_enabled: bool = True`, wired into `__init__`, `sync_from_restore`, `snapshot`, and `reset` exactly like the existing `emoji_counters`.

### 2. Daemon API + guard — `daemon/emoji/router.py`
- New `host_router` (`prefix="/api/{session_id}/host/emoji"`), mirroring the quiz/poll convention. No auth dependency — daemon host endpoints are localhost-only / authed at the Railway boundary. `session_id` is an unused path param.
  - `POST /global-toggle` → `EmojiGlobalStateResponse { emoji_global_enabled: bool }`. Flips the flag, persists via `save_session_state(get_active_session_folder(), participant_state.snapshot())`, returns the new value.
- Guard at the top of the existing `emoji_reaction` handler, right after the whitelist check and before the rate limiter / any forwarding:
  ```python
  if not participant_state.emoji_global_enabled:
      return Response(status_code=204)
  ```
  Sits ahead of both `addon_bridge_client.send_emoji` (overlay) and `notify_host` (host screen).

### 3. Router registration — `daemon/host_server.py`
`from daemon.emoji.router import host_router as emoji_host_router` + `app.include_router(emoji_host_router)`.

### 4. Host state bootstrap — `daemon/host_state_router.py`
`HostStateResponse` gains `emoji_global_enabled: bool = True`; `get_host_state` populates it from `ps.emoji_global_enabled`, so the badge renders the correct initial state on page load / reconnect.

### 5. Frontend — `static/host.html` + `static/host.js`
- Badge `#emoji-master-badge` in `.host-footer-left` after `#engagement-hover`, reusing existing badge classes — `.badge.connected` (green, enabled) / `.badge.disabled` (gray, disabled). **No new CSS.**
- `toggleEmojiGlobal()` POSTs to `API('/emoji/global-toggle')` and applies the returned state; `applyEmojiMasterBadge(enabled)` swaps the class + tooltip. The `state` WS/REST handler calls `applyEmojiMasterBadge(msg.emoji_global_enabled !== false)`.

### 6. Cleanup
Removed dead Railway helpers `send_emoji_to_host` + `_send_to_special` (`railway/shared/messaging.py`) — never called, and a latent unguarded emoji→host path.

## Out of scope (YAGNI)
Per-participant counter/block; UUID validation; fixing the pre-existing UUID leak; Claude auto-moderation; multi-host-tab live sync of the badge (a second host tab reflects the new state on its next `state` message / refresh).

## Testing
- Daemon unit tests (`tests/daemon/test_emoji_router.py`, `TestEmojiMasterSwitch`): OFF drops silently (204, no `notify_host`/overlay call, no counter bump); ON forwards; toggle flips + reports; flag round-trips through `snapshot()` → `sync_from_restore()`.
- OpenAPI contract snapshot regenerated for the new endpoint + schema; `API.md` regenerated from contracts.
- Manual screenshot proof of the badge enabled/disabled states.
