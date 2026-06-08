# Emoji Abuse Protection — Design

**Date:** 2026-06-08
**Status:** Approved (design); pending implementation plan

## Goal

Give the host two independent ways to stop emoji-reaction abuse during a live session:

1. **Global master switch** — a footer badge (❤️) next to the 👁 engagement eye. Green border = emojis enabled; click to disable (gray, grayscale). When disabled, no participant emoji reaches the host screen or desktop overlay.
2. **Per-participant block** — each participant row shows a `❤️ N` counter of emojis they've sent. Clicking it blocks that participant's emojis server-side (red + 🚫). Click again to unblock.

The two controls are independent: a per-participant block persists even when the global switch is re-enabled.

## Decisions

| Question | Decision |
|---|---|
| Global OFF behavior | Drop silently server-side (daemon early-returns before forwarding). |
| Persistence | Persist in `session-state.json` — survives daemon restart / session resume. |
| Blocked participant UX | Silent — their local send animation still plays; emoji is dropped. No error, no visual change on their screen. |
| Enforcement approach | **Approach A** — full server-side enforcement in the daemon emoji handler. The only approach that also suppresses the desktop overlay. |

## Architecture

Enforcement lives entirely in the daemon. The host browser only renders state and calls two toggle endpoints. The Railway backend stays a dumb proxy (no emoji-specific state there).

### 1. Data model

**`daemon/participant/state.py` — `ParticipantState`** (new fields):

```python
emoji_global_enabled: bool = True                            # session-wide master switch
emoji_blocked_uuids: set[str] = field(default_factory=set)   # per-participant blocks
participant_emoji_counts: dict[str, int] = field(default_factory=dict)  # uuid -> total sent
```

All three are included in `snapshot()` and restored in `sync_from_restore()` so they persist in `session-state.json`. A `set` serializes to a JSON list and restores back to a set.

**`session-state.json`** (new persisted keys):

```json
{
  "emoji_global_enabled": true,
  "emoji_blocked_uuids": ["uuid-bob"],
  "participant_emoji_counts": { "uuid-alice": 7, "uuid-bob": 23 }
}
```

**`daemon/host_state_router.py` — `HostParticipant`** (new fields):

```python
emoji_count: int = 0         # total emojis sent by this participant
emoji_blocked: bool = False  # whether their emojis are silently dropped
```

**Host state response** (`GET /api/{session_id}/host/state`) gains a top-level `emoji_global_enabled: bool` so the host can render the master badge's initial state.

### 2. Daemon API

A new `host_router` is added to `daemon/emoji/router.py`, matching the existing convention used by quiz / poll / debate (`prefix="/api/{session_id}/host/<domain>"`). Today that file only defines `participant_router`.

```python
# daemon/emoji/router.py
participant_router = APIRouter(prefix="/api/participant/emoji", ...)        # existing
host_router        = APIRouter(prefix="/api/{session_id}/host/emoji", ...)  # NEW

@host_router.post("/global-toggle")           # -> { "emoji_global_enabled": bool }
@host_router.post("/participant/{uuid}/block-toggle")  # -> { "emoji_blocked": bool }
```

Both require host auth, both call `save_session_state()` immediately after mutating state, and both return the new value (toggle semantics — the daemon flips and reports the result). The new `host_router` must be registered in `daemon/__main__.py`.

Responses use Pydantic models (per project convention), not raw dicts.

### 3. Emoji handler guard

In the existing `POST /api/participant/emoji/reaction` handler (`participant_router`, `status_code=204`), after the current rate-limit + whitelist checks, add silent-drop guards and a counter bump:

```python
# silent drop — 204 (no content) is indistinguishable to the participant
if not participant_state.emoji_global_enabled:
    return
if uuid in participant_state.emoji_blocked_uuids:
    return

# count the send (only counted when actually forwarded)
participant_state.participant_emoji_counts[uuid] = \
    participant_state.participant_emoji_counts.get(uuid, 0) + 1

# existing: forward to desktop overlay + host WS broadcast ...
```

Counts are bumped only for emojis that are actually forwarded (not for dropped ones), so the counter reflects emojis the host actually saw.

### 4. Frontend

**Footer master switch** — `static/host.html`, inside `.host-footer-left` right after `#engagement-hover`:

```html
<span id="emoji-master-badge" class="badge connected footer-tooltip-target"
      onclick="toggleEmojiGlobal()" style="cursor:pointer;font-size:1rem">❤️</span>
```

Reuses existing badge classes — no new footer CSS:
- enabled → `.badge.connected` (green border + tint)
- disabled → `.badge.disabled` (gray border, muted, 0.6 opacity)

**Per-participant counter** — `static/host.js` `renderParticipantList()`, in the `<li>` template (~line 1271), inserted just before `${scoreTag}`:

```js
const emojiCount = participant.emoji_count || 0;
const emojiBlocked = participant.emoji_blocked === true;
const emojiTag = (emojiCount > 0 || emojiBlocked)
  ? `<span class="pax-emoji${emojiBlocked ? ' blocked' : ''}"
        title="${emojiBlocked ? 'Blocked — click to unblock' : 'Click to block emojis'}"
        onclick="toggleEmojiBlock('${escHtml(pid)}')">❤️ ${emojiCount}${emojiBlocked ? ' 🚫' : ''}</span>`
  : '';
```

Badge hidden when count is 0 and not blocked (per the project's "hide zero-count badges" rule). New CSS in `host.css`: `.pax-emoji` (neutral pill) and `.pax-emoji.blocked` (red), ~6 lines.

**JS handlers** — `static/host.js`:

```js
async function toggleEmojiGlobal() {
  const r = await fetch(`/api/${sessionId}/host/emoji/global-toggle`, {method:'POST'});
  const {emoji_global_enabled} = await r.json();
  applyEmojiMasterBadge(emoji_global_enabled);  // swap connected/disabled class
}

async function toggleEmojiBlock(pid) {
  const r = await fetch(`/api/${sessionId}/host/emoji/participant/${pid}/block-toggle`, {method:'POST'});
  const {emoji_blocked} = await r.json();
  participantDataById[pid].emoji_blocked = emoji_blocked;
  renderParticipantList(cachedParticipantIds);
}
```

Master badge initial state comes from `emoji_global_enabled` in the host `/state` bootstrap. Live count increments come from the existing `emoji_reaction` WS message — on receipt, bump `participantDataById[uuid].emoji_count` and re-render the row.

## Open question (resolve during planning)

The existing `emoji_reaction` WS message sent to the host — does it currently include the sender's `uuid`? If not, add it so the host can attribute counts to the correct participant row. Verify against `daemon/ws_messages.py` (`EmojiReactionMsg`) when writing the implementation plan.

## Testing

- **Daemon unit tests** (fast, `tests/daemon/`): global toggle flips and persists; participant block toggle flips and persists; reaction handler silently drops (returns 204, does not forward) when global is off or sender is blocked; counts bump only on forwarded reactions; `snapshot()`/`sync_from_restore()` round-trip the three new fields.
- **OpenAPI contract**: regenerate the daemon OpenAPI snapshot for the two new host endpoints.
- **Frontend**: manual screenshot proof of the footer badge (enabled/disabled) and the participant counter (normal / blocked / hidden-at-zero).

## Out of scope (YAGNI)

- No rate-limit changes (the existing 15/min limiter stays).
- No per-emoji-type blocking (block is all-or-nothing per participant).
- No participant-facing "you are blocked" UI (silent by decision).
- No analytics/history of who was blocked when.
