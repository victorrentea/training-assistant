## Context

The tool runs as two processes: the public Railway gateway (`railway/`) serves pages and proxies API calls, and a local **daemon** (`daemon/`) owns all identity logic. The participant API is proxied Railway → daemon and keyed off the `X-Participant-ID` header (a per-participant **UUID**). Participant identity today:

- `POST /register` (`daemon/participant/router.py:490`): if the UUID is already known, returns the stored name idempotently (:499-504); empty body → auto-assigned fictional name (conference character pool :515-520, workshop LOTR pool :521-538); explicit name → **hard 409** if the name is already taken (:511-513). Name truncated to 32 chars (:508).
- `POST /rejoin` (:473): lookup-only restore for a returning UUID in the current session; 404 if unknown.
- `PUT /name` (:585): rename a registered participant; **hard 409** on duplicate (:604-606); name truncated to 32 chars (:599).
- Contracts: `RegisterRequest{name?, location?}`, `RenameRequest{name}` (:53-59). `RegisterResponse{name, avatar}` (:48).

State lives in the in-memory singleton `participant_state` (`daemon/participant/state.py`), which is a **cache** repopulated from Railway AppState via `sync_from_restore` on reconnect/restart and snapshotted to `session-state.json`. Real names must round-trip through this or they revert. The canonical attendee enumerator is `_build_host_participants_list()` (`daemon/host_state_router.py:127`) — **note it includes `uuid` per entry, and is host-only**. Session files live under `get_active_session_folder()` (`daemon/misc/content_files.py`) and are written with `atomic_write()` (`daemon/files_md.py:143`). Per-session (re)init happens in `daemon/__main__.py:1209-1272` (`participant_state.reset()` :1228, agenda refresh, `announce_session_id`).

**Broadcast infrastructure.** `broadcast(msg)` (`daemon/ws_publish.py:55`) sends a typed message to **all participants** via the Railway relay envelope. `notify_host(msg)` (`daemon/ws_publish.py:72`) sends only to connected host browsers. Today the roster is pushed via `_notify_host_participant_list()` (`daemon/participant/router.py:424`) using `notify_host` — **host-only**. There is currently **no participant-facing broadcast of participant names** (participants only ever learn the count). The participant client dispatches inbound WS messages in `_handleWsMessage` (`static/participant.html:3914`).

The frontend is vanilla HTML + inline JS (Tailwind, no bundler). The participant boot/gate is `loadParticipantState()` (`static/participant.html:3331`); the name editor is the crayon-triggered `_startNameEdit`/`_commitName` (:3221/:3235), where the current rename fetch silently swallows the 409 (:3249).

**Authoritative product decisions** (from the user, this revision — these SUPERSEDE the prior First+Last / live-warning / managed-region draft): identity = a **single free-text name** in the existing `name` field (no first/last, anywhere); the gate shows only when the server has no committed name for this UUID in the active session; **Enter** submits the typed name, **Anonymous** ignores it and uses the fictional path; uniqueness is checked **only on Enter**, is **reported but never blocks**, and there is **no live-typing warning and no confirm dialog**; an **in-session duplicate indicator** on the participant's own card is driven by a **UUID-free names-only broadcast**; `attendees.md` is **always fully regenerated**; host PDF is phase 2.

## Goals / Non-Goals

**Goals:**
- Gate admission on a single-field real-name screen when the server has no committed name for this UUID in the active session (first visit + new session), with an anonymous escape hatch.
- Reuse the single `name` field (raise cap 32 → 64) and the existing crayon rename UI — minimal new surface.
- Check uniqueness only on Enter; report duplicates via a soft flag but never block; remove the two hard 409s.
- Show a live, self-clearing in-session duplicate indicator on the participant's own profile card.
- Broadcast the roster's display **names** to all participants on any change — **without any UUID or stable id in the payload**.
- Always fully regenerate a live `attendees.md` from the roster; make names survive reconnect via `participant_state` / `session-state.json`.

**Non-Goals:**
- No separate username/handle, no first/last split, no auth, no email/identity verification.
- No live-while-typing duplicate check and no "are you sure" confirm dialog (both removed from the prior draft).
- No structured session metadata model (title/client/date stay folder-name-derived — see risks).
- No host PDF export in phase 1 (phase 2 capability `host-attendees-pdf`).
- No UUIDs (or any stable per-user id) in any participant-facing payload.

## Decisions

### 1. Single free-text name field → existing `name` field (no first/last)
The gate renders **one** free-text input with ghost/placeholder text and a short hint line stating the name will be used to produce the attendance sheet. There is no first/last split in UI, model, or storage. On **Enter**, the trimmed input is sent as the existing `name` in `RegisterRequest`/`RenameRequest`. The server truncation cap is raised **32 → 64** in both `register` (:508) and `rename` (:599). Downstream code (`_build_host_participants_list`, scoring, avatars) is untouched.

**Alternatives considered:** structured `first_name`/`last_name` fields (the prior draft) — rejected: touches the state cache, `sync_from_restore`, snapshot schema, host enumerator, and every consumer of `name` for no product benefit, and the user explicitly chose a single field.

### 2. Gate visibility keyed off "server has a committed name for this UUID"
The name screen is a full-screen overlay shown by `loadParticipantState()` **before** `_connectWS()`. The rule: **show the gate when the server has no committed name for this UUID in the active session.**
- **First visit** (unknown UUID) → gate shown.
- **Next-day / new session** (participant state was reset at `daemon/__main__.py:1209-1272`, so the UUID is no longer known) → gate shown.
- **Same-session reconnect** where the UUID already has a committed name → server returns that name (idempotent `register` :499-504 / `rejoin` :473) and the client **skips** the gate.
- **Anonymous** identities are still "committed names" for the UUID, so an anonymous participant who reconnects in the same session is **not** re-gated; the gate reappears for them next session like everyone else.

The gate must **fail open** (retry / anonymous) if register/rejoin fails — never a dead end.

**Browser close/reopen nuance (to verify):** within the same session, closing and reopening the browser keeps the same UUID in `localStorage`; the server should still hold the committed name, so the gate is skipped. This must be verified — if the UUID is regenerated or the server no longer has the name, the gate would (correctly) reappear. Recorded as a to-verify item, not a blocker.

**Alternatives considered:** a client-only `LS_CUSTOM_NAME_KEY` flag as the sole gate trigger (prior draft) — rejected as the authoritative signal because it desyncs from server state on new sessions and reconnects; the server's "do I have a committed name for this UUID" is the source of truth. A local flag may still be used as an optimization, but server state decides.

### 3. Two buttons: Enter (submit typed) and Anonymous (ignore typed)
- **Enter** — enabled **only when the input is non-empty**; submits the typed name via `register` (first visit) or `rename` (already-registered).
- **Anonymous** ("Enter as anonymous") — **ignores whatever is typed** and calls `register` with an **empty body**, reusing the existing fictional-name path (`daemon/participant/router.py:515-538`). It shows a **warning on hover and as a tooltip**: "You might not appear correctly in the attendance sheet." The `?as=Name` hook and hermetic tests keep working because they pre-seed a name and satisfy the gate without showing it.

### 4. Uniqueness: checked only on Enter, reported but never blocking
Duplicates are **permitted**. There is **no live-while-typing check and no confirm dialog** (both removed from the prior draft).

**On Enter (server-side):** `register`/`rename` compute `taken = {names} − {self}`, **always write the name**, and return a **soft conflict flag** — never a 409. The two hard 409 returns (`register` :511-513, `rename` :604-606) are **removed**.

**Exact contract:**
- `POST /register` → `RegisterResponse{name, avatar, name_conflict: bool}` (new optional `name_conflict`, default `false`). Never returns 409 for a taken name. `name_conflict=true` iff the accepted explicit name collided with another participant at write time.
- `PUT /name` → change from bare `204 No Content` to a success response carrying the flag: `200 OK` with body `{name_conflict: bool}` (symmetric with `register`, easiest client handling). Never returns 409.
- The 409-swallowing code at `participant.html:3249` is replaced with reading `name_conflict`; no blocking dialog is shown.

**Alternatives considered:** keep the live-typing warning + "Continue anyway" confirm from the prior draft — **removed** per the authoritative design; the live in-session indicator (Decision #6) replaces it and covers the more important case (a duplicate that arises *after* you entered).

### 5. Participant-facing names-only broadcast — KEY REQUIREMENT + SECURITY
This is **net-new**. Today participants never receive the name list (only the host does, via `notify_host`).

- Add a participant-facing message `participant_names_updated` carrying a **list of display names only** (e.g. `{type: "participant_names_updated", names: [...]}`), sent via `broadcast()` (`daemon/ws_publish.py:55`) on **any** roster change — join / rename / leave. Fire it alongside the existing host-facing `_notify_host_participant_list()` (called at `participant/router.py:580/610/640/661/690/833`).
- The participant client handles it in `_handleWsMessage` (`participant.html:3914`), storing the list and recomputing the duplicate indicator (Decision #6).

**SECURITY INVARIANT — no UUIDs in participant-facing payloads.**
Participant identity is the `X-Participant-ID` **UUID** header. If a participant learns another participant's UUID, they can **impersonate** them — send requests as them, bypass per-identity rate-limiting, and take over their identity. Therefore the names broadcast **MUST carry display names only, never UUIDs or any other stable per-user id.** The in-session duplicate detection is deliberately designed to need **no UUID** — it counts occurrences of the participant's *own* name in the list (Decision #6).

- The **host** roster (`_build_host_participants_list()`, which includes `uuid`) is fine to keep UUIDs — the host is trusted.
- An explicit task **audits every existing participant-facing WS/HTTP payload** for any UUID or other stable id and strips it if found.

### 6. In-session live duplicate indicator (client-side)
While a participant's name duplicates another name currently in the participant list, **their own** name display (the profile card at the bottom of the session view) shows all of:
- a slow **red blink**,
- a small **persistent underline** (not a tooltip),
- a **⚠️** warning-emoji prefix,
- the label **"duplicate"** (a.k.a. "non-unique"),
- a **"click here to change"** affordance that invokes the existing crayon edit (`_startNameEdit`/`_commitName`, :3221/:3235).

**Detection is UUID-free:** on each `participant_names_updated`, count how many times the participant's **own** name appears in the broadcast `names` list; **≥2 ⇒ duplicate**. No UUID or per-user id is needed or used.

**Self-clearing for both sides:** when either the participant or the previously-conflicting participant changes their name to make it unique, the server re-broadcasts the updated names list; **both** clients recompute their own count and the indicator clears wherever the count drops below 2. No special "who did I conflict with" bookkeeping is required — each client only reasons about its own name's count.

### 7. `attendees.md` lifecycle — always full regeneration (no managed region)
A Markdown file `attendees.md` is maintained in the active session folder alongside `session-state.json`, notes, `ai-summary.md`, `files.md`.
- **Always full-regenerate:** on **every** name set/change the daemon rewrites the **whole** file from the live roster. There is **no managed-region / trainer-hand-edit-preservation logic** (removed from the prior draft) — the file is a generated artifact.
- **Data source:** `_build_host_participants_list()` (`host_state_router.py:127`) — the canonical enumerator (all named participants, incl. offline, excl. `__`-prefixed internal ids).
- **Header:** derived from the session folder name + dates parsed by `_SESSION_FOLDER_RE` (`daemon/config.py`) + optional gdrive url — because there is no structured session metadata.
- **Body:** one line per attendee; anonymous/fictional entries are distinguishable from confirmed real names.
- **Write:** `atomic_write()` (`daemon/files_md.py:143`) into `get_active_session_folder()`.
- **Regeneration hook:** fire on the same roster-change points that call `_notify_host_participant_list()` (register/rename/leave).
- **Init/clear:** at per-session (re)init (`daemon/__main__.py:1209-1272`, near `participant_state.reset()` :1228) create/clear `attendees.md` for the new session.
- **Persistence:** names must round-trip through `participant_state` / `sync_from_restore` / `session-state.json` so the regenerated file survives reconnect/restart with the real names intact.

## Risks / Trade-offs

- **UUID leakage in a participant-facing payload = impersonation vector.** Mitigation: the names broadcast is names-only by construction, detection needs no UUID, and an explicit audit task sweeps all existing participant-facing payloads. This is the highest-severity concern in the change.
- **Real names revert on reconnect/restart if not persisted** → names must round-trip through `participant_state` and `session-state.json` (`sync_from_restore`); covered by a hermetic close/reopen test.
- **Gate visibility desync** (client thinks it's named but server doesn't, or vice-versa) → the server's "committed name for this UUID" is authoritative; browser close/reopen is a recorded to-verify item.
- **32 → 64 cap change could affect layout/avatars** → verify host roster and profile card render long names; avatars are name-independent for explicit names.
- **Broadcast storms on churn** (many joins/renames at once re-broadcast the full list) → acceptable at workshop scale; the payload is a small list of strings.
- **Race conditions on simultaneous same-name entry / concurrent rename / concurrent duplicate-resolution** → the always-succeed-and-flag contract plus the count-based indicator make these convergent (last write wins on the flag; every client recomputes from the latest broadcast). Explicitly covered by the race-condition tests (see tasks §8).
- **Header from folder name is lossy** (client/title/date encoded in a filename) → acceptable for phase 1; structured metadata is a separate future change.
- **Gate could trap a participant offline** (register/rejoin fails) → gate must fail open to the anonymous path or a retry, never a dead end.

## Migration Plan

- Additive backend: new optional `name_conflict` field on `RegisterResponse`; `PUT /name` becomes `200 OK` + `{name_conflict}`; remove the two 409 returns; add the `participant_names_updated` broadcast message (rides the generic `broadcast` envelope Railway relays — no `railway/**` change). Regenerate `docs/openapi.yaml` and WS YAMLs, then `API.md` via `python3 scripts/generate_apis_md.py --output API.md` (never hand-edit `API.md`).
- Frontend ships via the daemon hot-deploy path (push to `master` → `static_sync` uploads changed `static/` + `reload`), no Railway redeploy needed.
- Rollback: revert the change dir + restore the two 409 returns and the bare `204`; drop the `participant_names_updated` broadcast; `attendees.md` is a passive artifact with no phase-1 consumers, safe to leave.

## Open Questions

1. **Browser close/reopen within a session:** confirm the server still holds the committed name for the UUID (gate skipped) after a full browser close/reopen — the recorded to-verify item.
2. **`PUT /name` wire shape:** `200 OK` + `{name_conflict}` is the chosen default (symmetric with `register`); confirm no consumer relied on the bare `204`.
3. **Attendance header source:** confirm deriving title/client/date from the folder name + `_SESSION_FOLDER_RE` + optional gdrive url is acceptable given there is no structured session metadata.
4. **Indicator copy:** confirm the label wording ("duplicate" vs "non-unique") and the anonymous tooltip copy ("You might not appear correctly in the attendance sheet.").
