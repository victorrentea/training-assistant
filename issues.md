# Known Issues

## Critical / Security

- [ ] **XSS via poll question/options** — backend accepts raw strings; frontend renders with `innerHTML` in places. A participant or host could inject HTML.

- [ ] **No backend validation on participant name length** — frontend caps at 32 chars, but backend accepts arbitrarily long names.

---

## Major Bugs

- [ ] **Duplicate name collision** — two browser tabs with the same name both enter `state.participants`; closing one tab may drop both. Assign a UUID at first contact with the browser, which remains and is used as a primary key for the participant. The display name should just be used for rendering. In other words, the application should tolerate having duplicated user names, although it should avoid assigning the same name as previously explained in the requirements. 

- [ ] **Stale vote_times on reconnect** — `vote_times` is never cleaned up on disconnect, so old timestamps skew scoring when a participant rejoins.

- [ ] **Vote option IDs not validated on reconnect** — if a participant restores a vote from `localStorage`, the option IDs might no longer exist in the current poll.

- [ ] **Multi-vote option list not bounded on backend** — no check that `option_ids` list isn't massive; a malicious client could send 1000 option IDs.

---

## Moderate / UX Breakage

- [ ] **Timezone strings sent to Nominatim geocoder** — `"America/New_York"` is not a valid geocoding query; all timezone-only locations silently fail to appear on the map.

- [ ] **Timer race condition** — if two `timer` messages arrive quickly, old interval may not clear before the new one starts.

- [ ] **Poll state not re-synced on WebSocket reconnect** — reconnect only resends the participant name; if the poll changed during disconnect, participant sees stale state until next broadcast.

- [ ] **Base scores never cleared on poll close/delete** — can bleed into subsequent polls if the host rapidly toggles.

---

## Minor Glitches

- [ ] **Vote percentages can sum to 101%** — `Math.round` on each bar independently can round up more than once.

- [ ] **Geolocation timeout vs. permission denial not distinguished** — host sees both as absence of location with no differentiation.

- [ ] **LLM hints cache key uses raw question string** — special characters could cause localStorage key collisions.

- [ ] **`suggested_names` set grows unbounded** — names handed out but never connected are never purged.

- [ ] **No fetch request timeouts** — slow network can hang the UI indefinitely with no user feedback.

- [ ] **Host can toggle correct options with 0 votes** — no guard prevents marking answers on an empty poll (harmless but confusing).

- [ ] **QR code renders using raw CSS variable values** — if a CSS variable is malformed, QR code silently fails.
