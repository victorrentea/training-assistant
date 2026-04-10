## 1. Daemon — Participant State

- [ ] 1.1 Add `cities: dict[str, str]` field to `ParticipantState` in `daemon/participant/state.py`
- [ ] 1.2 Include `cities` in `to_dict()` serialization and `from_dict()` / `reset()` in `ParticipantState`

## 2. Daemon — Reverse Geocoding

- [ ] 2.1 Add async helper `resolve_city(lat: float, lon: float) -> str` in `daemon/participant/geocoding.py` using `httpx.AsyncClient` with `Accept-Language: en` and a 5s timeout; return `""` on any error
- [ ] 2.2 In `set_location` endpoint (`daemon/participant/router.py`): detect coordinate pattern; if matched, spawn `asyncio.create_task` that calls `resolve_city`, stores result in `participant_state.cities[pid]`, then re-notifies host via `_notify_host_participant_list()`
- [ ] 2.3 For non-coordinate location strings, store the value directly in `participant_state.cities[pid]` (no Nominatim call needed)

## 3. Daemon — Broadcast City Field

- [ ] 3.1 Include `city` field (from `participant_state.cities.get(pid, "")`) in the `participant_location` event payload
- [ ] 3.2 Include `city` field in the `participant_registered` event payload
- [ ] 3.3 Ensure `city` is included in the full participant state sync sent to the host on WS connect/reconnect

## 4. Frontend — Remove Browser Geocoding

- [ ] 4.1 In `host.js`, remove the lazy Nominatim reverse-geocode loop (lines ~1504-1521) from the participant list renderer
- [ ] 4.2 In `host.js`, use `participant.city || participant.location || ''` as the location label for display in the participant list (replacing `resolvedCities[loc]` lookup)
- [ ] 4.3 Remove the `resolvedCities` cache object from `host.js` if no longer used elsewhere (check `geocode()` function — forward geocoding for map view is separate and stays)

## 5. Verification

- [ ] 5.1 Join as a participant with geolocation enabled — confirm host shows resolved city without browser network calls to nominatim.openstreetmap.org
- [ ] 5.2 Confirm daemon logs show the Nominatim call (add a `log.info` in the geocoding helper)
- [ ] 5.3 Confirm graceful fallback: if Nominatim is unreachable, host shows raw coords
