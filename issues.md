# Known Issues

## Critical / Security

- [x] **XSS via poll question/options** — escaped with `escHtml()` in both participant.js and host.js before innerHTML insertion.

- [x] **No backend validation on participant name length** — backend now truncates to 32 chars in ws.py.

---

## Major Bugs

- [ ] **Duplicate name collision** — two browser tabs with the same name both enter `state.participants`; closing one tab may drop both. Assign a UUID at first contact with the browser, which remains and is used as a primary key for the participant. The display name should just be used for rendering. In other words, the application should tolerate having duplicated user names, although it should avoid assigning the same name as previously explained in the requirements. 

- [x] **Stale vote_times on reconnect** — `vote_times` entry cleared on WebSocket disconnect.

- [ ] **Vote option IDs not validated on reconnect** — if a participant restores a vote from `localStorage`, the option IDs might no longer exist in the current poll.

- [x] **Multi-vote option list not bounded on backend** — capped at `correct_count` (or total options), duplicates rejected.

---

## Moderate / UX Breakage

- [ ] **Timezone strings sent to Nominatim geocoder** — `"America/New_York"` is not a valid geocoding query; all timezone-only locations silently fail to appear on the map.

- [x] **Timer race condition** — `_startParticipantCountdown` already calls `clearInterval` before starting a new interval; was a non-issue.

- [x] **Poll state not re-synced on WebSocket reconnect** — `send_state_to(websocket)` is called on every connect; was already handled.

- [x] **Base scores never cleared on poll close/delete** — `base_scores` and `vote_times` now reset in `clear_poll()`.

---

## Minor Glitches

- [x] **Vote percentages can sum to 101%** — fixed with largest-remainder rounding in participant.js.

- [ ] **Geolocation timeout vs. permission denial not distinguished** — host sees both as absence of location with no differentiation.

- [ ] **LLM hints cache key uses raw question string** — special characters could cause localStorage key collisions. > assign uuids to options

- [x] **`suggested_names` set grows unbounded** — set cleared when it exceeds 50 entries.

- [ ] **No fetch request timeouts** — slow network can hang the UI indefinitely with no user feedback.

- [ ] **Host can toggle correct options with 0 votes** — no guard prevents marking answers on an empty poll (harmless but confusing).

- [ ] **QR code renders using raw CSS variable values** — if a CSS variable is malformed, QR code silently fails.
