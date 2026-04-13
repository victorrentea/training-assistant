## Why

The host browser currently calls Nominatim directly to reverse-geocode participant `lat,lon` coordinates into city names. This triggers CORS blocks from `localhost:1234` and 429 rate-limit errors because every page render re-issues calls for all visible participants. Moving geocoding to the daemon (server-side, once per participant) eliminates both problems.

## What Changes

- **Remove** browser-side Nominatim reverse-geocode calls from `host.js`
- **Add** server-side reverse-geocoding in the daemon when a participant's location is received
- **Store** the resolved city label alongside the raw coordinates in `participant_state`
- **Broadcast** the resolved label to the host, so host.js can display it directly without any further HTTP calls
- Participant's raw `lat,lon` is still stored (needed for map pins); resolved city label is a separate field

## Capabilities

### New Capabilities

- `participant-geocoding`: Daemon resolves participant `lat,lon` to a human-readable city/country label via Nominatim, once per participant registration, stored in participant state and pushed to the host.

### Modified Capabilities

- `session`: Participant state shape gains a `city` field (resolved label) alongside `location` (raw coords).

## Impact

- `daemon/participant/router.py` — `set_location` endpoint triggers async Nominatim call
- `daemon/participant/state.py` — add `cities: dict[str, str]` (pid → resolved label)
- `static/host.js` — remove lazy Nominatim fetch loop; use preresolved label from participant data
- New dependency: daemon makes outbound HTTP to `nominatim.openstreetmap.org` (already used indirectly via browser)
- Forward geocoding in `geocode()` (used for the map view) is **not** changed — it stays in the browser for now
