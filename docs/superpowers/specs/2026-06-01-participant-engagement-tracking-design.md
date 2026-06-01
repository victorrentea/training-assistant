# Participant Engagement Tracking — Design

**Date:** 2026-06-01
**Status:** Approved design, ready for implementation planning

## Goal

Give the host real-time and cumulative observability into how participants
actually *use* the participant app during a live workshop: how long they
actively spend on each view (slides, notes, summary, files, …), how many times
they open each view, and how many clicks they make inside it.

This serves the core product goal — maximizing engagement of a tired, bored,
distracted audience. The host gets:

- a **live pulse**: how many participants are genuinely engaged *right now*, and
  on which view; and
- **cumulative analytics**: total active time / visits / clicks per view across
  the whole session.

Both are surfaced through one new footer badge in the host UI, modeled on the
existing `slides-log-badge` (collapsed icon+count, hover popover with a
breakdown).

## Definitions

- **Active time** — wall-clock time during which *all* of the following hold:
  - `document.visibilityState === 'visible'` (the tab is foregrounded, not
    buried in a tab stack or minimized), and
  - the last human interaction (`mousemove`, `click`, `scroll`, `keydown`,
    `touchstart`) occurred within the **idle window of 60s**.
  Time is attributed to the **currently selected view** (the one shown by
  `showView`).
- **Idle** — no qualifying interaction for 60s. The clock stops; nothing is sent.
  *Known trade-off:* a participant intently watching auto-advancing slides
  without moving the mouse reads as idle. For a live workshop this is the
  intended behavior — we want a genuine engagement signal, not "a tab is open."
- **Visit** — counted once each time `showView(name)` *changes* the selected
  view while the document is visible (i.e. a deliberate navigation). The initial
  view restored from `localStorage` on page load does **not** count as a visit;
  only an actual change from the current view does.
- **Click** — any `click` event fired while a view is the active view, attributed
  to that view (single delegated listener).
- **Flush** — a `POST` of the per-view deltas accumulated since the last flush.
  Fires at most every **30s** while active time has accrued, plus on
  `visibilitychange → hidden` and on `pagehide`. No flush is sent when nothing
  accrued — idle/backgrounded tabs are silent.
- **Active now (host-derived)** — a participant counts as active *now* if their
  most recent flush reached the daemon within a **freshness window of 75s**
  (≈ 30s flush cadence + slack). Computed entirely in the host browser from the
  `last_active_at` timestamp, so the badge decays to 0 on its own when the room
  goes quiet — no server-side sweep, Railway stays a dumb proxy.

## Scope

**In scope**

- Per-participant, per-view metrics: `{ seconds, visits, clicks }`.
- All 8 participant views tracked uniformly via the single `showView` hook:
  `slides`, `notes`, `summary`, `files`, `agenda`, `activity`, `upload-paste`,
  `feedback`.
- One new REST endpoint for activity reports.
- Persistence of cumulative metrics in session state (survives daemon restart).
- One new host footer badge with live count + cumulative breakdown popover.

**Out of scope**

- Per-slide / per-file granularity (the existing `slides-log` badge already
  covers trainer-driven slide-time; this feature is about *which view* a
  participant is in, not which slide).
- Historical time-series charts. Only current cumulative totals + live pulse.
- Any new state on the Railway backend (it remains a pure proxy).

## Architecture

Chosen approach: **client accumulates locally, flushes deltas every 30s; host
derives the live pulse from `last_active_at`.**

Rejected alternatives:
- *Raw event stream* (send every click/view-enter, server computes time) —
  chatty, server-side idle math is fiddly.
- *Heartbeat-only* (tick "current view" every N seconds, server counts ticks) —
  simpler client but time resolution is bounded by the heartbeat interval, and
  visits/clicks still need a separate channel.

Data flow:

```
participant.html (Engagement module)
   │  every ≤30s while active, + on hide/unload (fetch keepalive)
   ▼
POST /{session}/api/participant/activity   (X-Participant-ID header)
   │  proxied verbatim by Railway (dumb proxy)
   ▼
daemon participant router
   │  merge deltas → PersistedParticipant.engagement
   │  bump runtime last_active_at / last_view (ephemeral)
   │  (cumulative engagement persisted by the 3s periodic snapshot loop)
   │  notify host via existing participant_list_updated message
   ▼
host.js
   │  stores per-participant engagement snapshot
   │  local 1–2s ticker computes "active now" from last_active_at
   ▼
footer badge  👁 N active  +  hover popover breakdown
```

## Component 1 — Client tracker (`participant.html`)

A single self-contained `Engagement` module, added **inline in
`participant.html`** to match that file's all-inline structure (host.js is a
separate file, but the participant page keeps everything in one HTML file).

Responsibilities:

- Maintain in-memory per-view accumulators
  `{ <view>: { seconds, visits, clicks } }` plus `pendingDeltas` (not yet
  flushed) and the active-view name.
- Track `lastInteractionAt`, updated by listeners on `mousemove`, `click`,
  `scroll`, `keydown`, `touchstart` (passive listeners).
- A 1s ticker: if visible and `now - lastInteractionAt < 60s`, add 1s of active
  time to the current view's accumulator (and pending delta).
- Hook into the existing `showView(name)` (participant.html:2016): on view
  change, the new view gets a `visit++` (when visible); the active-view pointer
  moves so subsequent seconds/clicks attribute correctly.
- One delegated `click` listener increments the current view's `clicks`.
- Flush loop: a 30s timer POSTs `pendingDeltas` when non-empty, then clears them.
  Also flush on `visibilitychange → hidden` and `pagehide`, using
  `fetch(url, { method:'POST', keepalive:true, headers:{...}, body })` so the
  request survives unload while still carrying the `X-Participant-ID` header.
- Reuses existing identity/session globals: `_myUUID` (participant.html:2159)
  and `_sessionId` (participant.html:2143).

Isolation: the module exposes nothing beyond a small init call and the
`showView` hook; it can be reasoned about and tested independently of the rest
of the page.

## Component 2 — Transport contract

New endpoint, mirroring every other participant action (REST POST, daemon-owned,
Railway-proxied, `X-Participant-ID` header):

```
POST /{session_id}/api/participant/activity
Header: X-Participant-ID: <uuid>
Body (Pydantic ActivityReportRequest):
{
  "current_view": "slides",
  "deltas": {
    "slides": { "seconds": 28, "visits": 1, "clicks": 3 },
    "notes":  { "seconds": 2,  "visits": 0, "clicks": 0 }
  }
}
Response: 204 No Content (or minimal ack)
```

`ViewEngagementDelta` = `{ seconds: int >= 0, visits: int >= 0, clicks: int >= 0 }`.
`deltas` keys are validated against the known view names; unknown views are
ignored (forward-compatible if a view is renamed). Contract defined as strict
Pydantic models; `API.md` regenerated from contracts (never hand-edited).

## Component 3 — Daemon aggregation & persistence

**Model** (`daemon/persisted_models.py`):

```python
class ViewEngagement(PersistedModel):
    seconds: int = 0
    visits: int = 0
    clicks: int = 0

class PersistedParticipant(PersistedModel):
    name: str | None = None
    avatar: str | None = None
    score: int | float | None = None
    location: str | None = None
    engagement: dict[str, ViewEngagement] = {}   # view -> cumulative metrics
```

This is **additive and backward-compatible**: existing `session-state.json`
files lack `engagement`, so it defaults to `{}` on load — no migration step
needed. (Consistent with the project rule to consider data-migration impact:
impact here is none.)

**Runtime state** (`daemon/participant/state.py`, `ParticipantState`): add
`last_active_at: dict[uuid, float]` and `last_view: dict[uuid, str]`. These are
ephemeral (not required to persist; rebuilt as reports arrive).

**Handler** (`daemon/participant/router.py`): new `POST .../activity` handler:
1. Resolve participant UUID from `X-Participant-ID`.
2. Merge each delta into `participants[uuid].engagement[view]`
   (`seconds/visits/clicks += delta`).
3. Update `last_active_at[uuid] = now`, `last_view[uuid] = current_view`.
4. `save_session_state(...)` (the existing periodic-save path already batches;
   reuse it rather than forcing a synchronous disk write per report if that
   matches existing cadence).
5. Notify the host by calling the existing `_notify_host_participant_list()`
   (the same path `register`/`rename` already use). **No new WS message type is
   introduced** — engagement rides along on the existing `participant_list_updated`
   message, whose `participants` field is already an untyped
   `list[dict[str, Any]]`. `_build_host_participants_list()` is extended to add
   three keys to each participant entry: `engagement` (view → {seconds, visits,
   clicks}), `last_active_at` (epoch ms, server-stamped), and `last_view`.

This deliberately avoids adding to the AsyncAPI specs (`docs/host-ws.yaml`) and
the WS-contract test (`tests/daemon/test_ws_contract.py`) — the contract surface
stays unchanged.

**Host load** (`daemon/host_state_router.py`): the same three keys are added in
`_build_host_participants_list()`, so the `participants` array of the
`HostStateResponse` returned by `GET /api/{session}/host/state` already carries
engagement and a freshly opened/reloaded host page is immediately populated.
`HostParticipant` gains the matching optional typed fields for contract honesty
(this changes the daemon OpenAPI schema → regenerate `docs/openapi.yaml`).

**Timestamp note:** `last_active_at` is stamped by the daemon as epoch
milliseconds; the host compares it against its own `Date.now()`. The host UI and
daemon run on the same machine (host REST → `localhost:8081`), so the clocks are
identical and there is no skew to correct for. Only the cumulative `engagement`
dict is persisted to `session-state.json`; `last_active_at`/`last_view` live only
in runtime `ParticipantState` and are rebuilt as reports arrive.

## Component 4 — Host UI

**`host.html`** — new badge in `.host-footer-left` (next to `summary-badge`),
mirroring `slides-log-badge`'s markup: a hover wrapper + badge (icon + count
span) + popover container.

```
<div id="engagement-hover" class="slides-catalog-hover" style="position:relative;">
  <span id="engagement-badge" class="badge empty footer-tooltip-target" style="...; gap:.35rem;">
    👁 <span id="engagement-count"></span>
  </span>
  <div id="engagement-popover" class="slides-catalog-popover activity-log-popover">
    <div id="engagement-content" class="slides-catalog-content"></div>
  </div>
</div>
```

**`host.css`** — reuse existing `.badge`, `.badge.empty`, `--badge-fill` hover,
`.slides-catalog-popover` / `.activity-log-popover` rules. No new badge visual
treatment (consistent-badge-styling rule).

**`host.js`**:
- Store the per-participant engagement snapshot received via the new WS message
  and via `/host/state` on load.
- A local ticker (every 1–2s) recomputes **active now**: participants whose
  `last_active_at` is within the 75s freshness window, grouped by `last_view`.
- **Badge headline**: `👁 <N>` where N = active-now count. When N is 0, render
  just the `👁` icon with the `.empty` class and no number (honors the
  "hide count badges when value is 0; never show 0" rule).
- **Popover** (reuse `_makeHover` mechanism, host.js:1010): header line
  `Live: <N> of <total> active now`, then one row per view sorted by cumulative
  active time:
  `<view>   <Xm Ys> · <V> visits · <C> clicks`, summed across all participants.
  Use the existing `_fmtSecs` helper for time formatting.
- Tooltip via `_setFooterBadgeTooltip` (host.js:67) summarizing live count.

## Edge cases

- **Tab hidden mid-view** → flush pending, stop the clock; resume on
  `visibilitychange → visible`.
- **Unload / navigate away** → `pagehide` flush with `keepalive`.
- **Clock skew** → `last_active_at` is stamped server-side (daemon `now`), not
  trusted from the client, so the live pulse is immune to client clock skew.
- **Rejoin / reconnect** → cumulative engagement is keyed by UUID in session
  state and simply continues accumulating.
- **Multiple tabs, same participant** → both report under the same UUID; deltas
  sum. Acceptable (rare in practice; not worth de-duping).
- **Session clear / new session** → engagement lives in `session-state.json` for
  that session; a new session starts fresh. Existing "Clear" semantics are
  unchanged by this feature.

## Testing & proof

- **Daemon unit test**: POST activity deltas → assert merge into
  `PersistedParticipant.engagement`, `last_active_at`/`last_view` updates, and
  host-notify payload shape.
- **Contract**: regenerate `API.md` via
  `python3 scripts/generate_apis_md.py --output API.md`; update the OpenAPI
  snapshot test if the daemon REST contract test catches the new endpoint.
- **Docs**: update `ARCHITECTURE.md` (data flow + new message), `backlog.md`
  (feature entry).
- **Visual proof**: screenshot of the live host footer badge with a populated
  breakdown popover.
- **Optional hermetic e2e**: a Docker/Playwright scenario driving a participant
  through a few views and asserting the host badge/popover updates.

## Defaults chosen (flag if you disagree)

- `Engagement` JS lives **inline in `participant.html`** (matches file structure).
- **All 8 views** tracked uniformly via the `showView` hook.
- Flush interval **30s**; idle window **60s**; host freshness window **75s**
  (all single constants, easy to tune).
- Per-participant per-view storage in `PersistedParticipant.engagement`
  (enables future per-participant drill-down at negligible size cost).
