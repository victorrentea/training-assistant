## Context

Participants submit their geolocation (`lat,lon`) via the Railway backend to the daemon's `/location` endpoint. The daemon stores the raw string and broadcasts it to the host. The host browser then calls Nominatim directly to resolve coordinates to a city name — this fails with CORS on localhost and causes 429 rate limiting on production because the call is re-issued on every participant list render.

The daemon already runs server-side Python with full outbound HTTP access and no CORS restrictions. It is the natural place to own a single, cached geocoding call per participant.

## Goals / Non-Goals

**Goals:**
- Daemon resolves `lat,lon` → city label via Nominatim once per participant per session
- Resolved label is stored in `participant_state` and broadcast to the host alongside raw coords
- Host.js removes its lazy Nominatim loop entirely for participant location display

**Non-Goals:**
- Forward geocoding (`geocode()` in host.js for map pins from city name) — stays in browser for now
- Caching across sessions — session state resets on new session; geocoding is cheap enough per-session
- Handling non-coordinate location strings (timezone-only, city name) — those are already human-readable and don't need geocoding

## Decisions

**Async geocoding in `set_location` endpoint**
The daemon's FastAPI endpoint calls Nominatim via `httpx.AsyncClient` (or `asyncio` + `httpcore`) after storing the raw location, then updates `cities[pid]` and notifies the host again with the resolved label. This keeps the HTTP response fast (returns immediately after storing raw loc) while geocoding happens in the background via `asyncio.create_task`.

Alternative considered: synchronous geocoding before returning → blocked participant's POST for ~200-500ms. Rejected: unnecessary latency.

**Store resolved label in `participant_state.cities: dict[str, str]`**
A separate dict (parallel to `locations`) avoids touching the raw location data. The host receives both: `location` (raw, for map pins) and `city` (resolved label, for display).

Alternative: overwrite `locations[pid]` with resolved label → loses raw coords needed for map. Rejected.

**Skip geocoding for non-coordinate locations**
If `location` doesn't match `^-?\d+\.?\d*,\s*-?\d+\.?\d*$`, it's already a human-readable string — store it directly as `cities[pid]` too (so host can always use `city` field for display).

**Use `httpx` (already in daemon dependencies)**
Daemon uses `httpx` elsewhere. Reuse it. Add `Accept-Language: en` header same as browser did.

## Risks / Trade-offs

- [Nominatim ToS] Rate limit: 1 req/sec max. With `asyncio.create_task`, concurrent joins could burst. → Mitigation: add a simple semaphore (1 concurrent Nominatim call) or accept occasional 429s (result falls back to raw coords display).
- [Nominatim down] Geocoding fails → `cities[pid]` stays unset, host shows raw coords as before. → Acceptable degradation.
- [Extra outbound call] Daemon now makes HTTP calls on participant join. → Low volume (one per participant per session, workshops have 20-100 participants).

## Migration Plan

1. Add `cities` dict to `ParticipantState` (serialize/deserialize alongside `locations`)
2. Add async geocoding logic in `set_location` endpoint
3. Include `city` field in participant data broadcast to host (`participant_location` and `participant_registered` events, and full state sync)
4. Remove lazy Nominatim loop from `host.js` participant list renderer; use `city` field instead
5. Deploy — no data migration needed (cities dict starts empty, fills on next participant join)
