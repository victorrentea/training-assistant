# Phase 1 — Core (single-field real-name join, anonymous, non-blocking duplicates, live names broadcast, attendees.md)

## 1. Backend — single-field name + non-blocking duplicate contract

- [x] 1.1 In `POST /register` (`daemon/participant/router.py:490`), remove the duplicate 409 (:511-513): accept the explicit name even when taken and compute a boolean `taken = names − self` conflict flag.
- [x] 1.2 Add optional `name_conflict: bool = False` to `RegisterResponse` (:48); return it `true` iff the accepted explicit name collided at write time.
- [x] 1.3 In `PUT /name` (:585), remove the duplicate 409 (:604-606); accept the rename even when taken and return the soft flag — change the response from bare `204` to `200 OK` with body `{name_conflict: bool}`.
- [x] 1.4 Raise the name truncation cap from 32 to 64 in both `register` (:508) and `rename` (:599).
- [x] 1.5 Keep the returning-participant idempotent path (:499-504) and `POST /rejoin` (:473) unchanged in contract so a known UUID still returns its stored (real or anonymous) name — this is what lets the client skip the gate on same-session reconnect.
- [x] 1.6 Keep the empty-body fictional-name path (:515-538) intact — it is what the Anonymous button reuses.

## 2. Backend — participant-facing names broadcast + UUID security audit (KEY REQUIREMENT)

- [x] 2.1 Add a participant-facing WS message `participant_names_updated` carrying a **list of display names only** (no UUIDs, no ids), as a typed Pydantic model.
- [x] 2.2 Emit it via `broadcast()` (`daemon/ws_publish.py:55`) on **every** roster change — join / rename / leave — alongside the existing host-facing `_notify_host_participant_list()` (fired at `participant/router.py:580/610/640/661/690/833`).
- [x] 2.3 **SECURITY:** ensure the names broadcast contains **no UUID or any stable per-user id** — display names only.
- [x] 2.4 **AUDIT** every existing participant-facing WS/HTTP payload for any UUID / stable-id leakage and strip it if found. (The host roster `_build_host_participants_list()` may keep `uuid` — host is trusted; participant-facing payloads may not.)

## 3. Backend — attendees.md always-regenerate lifecycle

- [x] 3.1 Add a helper that renders the **whole** `attendees.md` from `_build_host_participants_list()` (`daemon/host_state_router.py:127`) — one row per named attendee, marking anonymous/fictional entries distinctly; write with `atomic_write()` (`daemon/files_md.py:143`) into `get_active_session_folder()` (`daemon/misc/content_files.py`). **Always full regeneration — no managed-region / hand-edit-preservation logic.**
- [x] 3.2 Derive the `attendees.md` header from the session folder name + date(s) parsed by `_SESSION_FOLDER_RE` (`daemon/config.py`) + optional gdrive url (no structured session metadata exists).
- [x] 3.3 Regenerate `attendees.md` on every name set/change — the same roster-change points that call `_notify_host_participant_list()` — so it stays live on register / rename / leave.
- [x] 3.4 Initialize/clear `attendees.md` at per-session (re)init in `daemon/__main__.py:1209-1272` (near `participant_state.reset()` :1228) so a new session starts clean.

## 4. Backend — real names survive reconnect/restart

- [x] 4.1 Verify real names round-trip through `participant_state` (`daemon/participant/state.py`) and `sync_from_restore` so they are not reverted on reconnect/restart, and are captured in the `session-state.json` snapshot (so the regenerated `attendees.md` keeps the real names).

## 5. Frontend — participant join gate: single field + Enter/Anonymous (`static/participant.html`)

- [x] 5.1 Build a full-screen name-gate overlay with a **single free-text name input** (ghost/placeholder text) plus a short hint line stating the name will be used to produce the attendance sheet; follow `static/DESIGN-new-participant.md`. No first/last, no separate fields.
- [x] 5.2 Add an **Enter** button enabled **only when the input is non-empty** (disable on empty/whitespace-only); on click, submit the typed name via `register` (first visit) or `rename` (already-registered), then proceed to `_connectWS()`.
- [x] 5.3 Add an **Anonymous** button ("Enter as anonymous") that **ignores the typed input** and calls `register` with an **empty body** (fictional-name path :515-538); show a warning **on hover and as a tooltip**: "You might not appear correctly in the attendance sheet."
- [x] 5.4 In `loadParticipantState()` (:3331), show the gate **before** `_connectWS()` only when the server has **no committed name for this UUID** in the active session (first visit + new session); **skip** the gate on same-session reconnect when `register`/`rejoin` returns a stored name.
- [x] 5.5 Preserve the `?as=Name` hook (:3347): a pre-seeded name satisfies the gate without showing it (keep hermetic sequence tests green).
- [x] 5.6 Ensure the gate **fails open** (retry / anonymous) if register/rejoin fails — never a dead end.

## 6. Frontend — in-session duplicate indicator + rename (`static/participant.html`)

- [x] 6.1 Handle the new `participant_names_updated` message in `_handleWsMessage` (:3914): store the names list and recompute the duplicate indicator.
- [x] 6.2 Detect duplicate by counting the participant's **own** name's occurrences in the broadcast list (≥2 ⇒ duplicate) — **no UUID used**.
- [x] 6.3 On duplicate, show on the participant's **own** profile card: slow red **blink** + persistent **underline** + **⚠️** prefix + label **"duplicate"** + a **"click here to change"** affordance.
- [x] 6.4 The "click here to change" affordance invokes the existing crayon edit (`_startNameEdit`/`_commitName`, :3221/:3235) at the bottom of the session.
- [x] 6.5 Clear the indicator automatically when the own-name count drops below 2 (works for **both** the participant and the previously-conflicting one, since each recomputes from the re-broadcast list).
- [x] 6.6 In `_commitName` (:3235), replace the swallowed 409 handling (:3249) with reading `name_conflict` from the response; do **not** show any blocking dialog (no live-typing warning, no confirm).

## 7. Docs & API reference

- [x] 7.1 Update source contracts (Pydantic models / OpenAPI / WS specs) for the `name_conflict` field, the `PUT /name` `200`+`{name_conflict}` response, and the new `participant_names_updated` WS message; regenerate `docs/openapi.yaml` (and WS YAMLs).
- [x] 7.2 Regenerate `API.md` via `python3 scripts/generate_apis_md.py --output API.md` (never hand-edit `API.md`); record the change in `backlog.md`.

## 8. Tests — comprehensive END-TO-END (first participant contact; make this prominent)

Because the join gate is the participant's **first contact** with the app, tests must be comprehensive and end-to-end, and must explicitly cover race conditions.

- [x] 8.1 First-visit gate: opening a fresh session URL shows the single-field gate before the socket connects.
- [x] 8.2 Enter with a name: typing a name and clicking Enter registers that exact name and admits the participant.
- [x] 8.3 Anonymous ignores typed text: typing a name then clicking Anonymous registers a **fictional** name (not the typed text) and admits; the hover/tooltip warning is present.
- [x] 8.4 Duplicate detection + indicator: two participants with the same name each show the blink + underline + ⚠️ + "duplicate" + click-to-change on their **own** card.
- [x] 8.5 Resolve-from-either-side clears both: when **either** duplicate renames to a unique name, the indicator clears for **both** participants (both recompute from the re-broadcast list).
- [x] 8.6 Rename via crayon: the existing crayon edit renames, updates the roster/broadcast, and (if now unique) clears the indicator.
- [x] 8.7 Returning-participant skip: a participant who already has a committed name for their UUID rejoins **within the same session** and does **not** see the gate.
- [x] 8.8 Gate reappears on new session: after per-session (re)init, the same UUID sees the gate again.
- [x] 8.9 **SECURITY:** assert the `participant_names_updated` payload (and other participant-facing payloads) contain **no UUID / stable id** — names only.
- [x] 8.10 **RACE CONDITIONS / simultaneous changes:** (a) two participants Enter the **same** name at once — both admitted, both flagged, no 409; (b) two participants rename simultaneously — roster converges and each client recomputes correctly; (c) a duplicate resolved **concurrently by both** — indicator ends cleared for both (no stuck indicator).
- [x] 8.11 Persistence E2E: a real name set at the gate survives session close + reopen (round-trips through `participant_state` / `session-state.json`); `attendees.md` keeps the real names. Mark slow tests `@pytest.mark.nightly`.
- [x] 8.12 Attendees file: `attendees.md` is fully regenerated on register + rename + leave, reset on session (re)init, header derives from the folder name, and anonymous entries are distinguishable.
- [x] 8.13 Run `bash tests/run-daemon-tests.sh` and `bash tests/docker/run-hermetic.sh`; capture evidence.

---

# Phase 2 — LATER (host download + PDF) — NOT part of phase-1 delivery

## 9. Host attendees download + PDF (deferred)

- [ ] 9.1 Add a host-only daemon endpoint that serves the active session's `attendees.md` content (no server error when no session is active).
- [ ] 9.2 Add a host UI download control mirroring `downloadKeyPoints()` (`static/host.js:1227`) to fetch the raw `attendees.md`.
- [ ] 9.3 Add client-side Markdown-to-PDF rendering reusing the `marked` + `window.print()` pattern (`downloadSummaryPdf()` `participant.html:4631`) to produce a printable attendance sheet.
- [ ] 9.4 Tests for the host endpoint + a smoke test of the PDF/print render path.
