# Tracing & Location Cleanup — Design Spec

## Goal

Three targeted improvements to reduce noise in extracted sequence diagrams and clean up the participant registration flow.

## Change 1: GDrive Mock in OTel Tracing

**Problem:** The daemon→Railway→GDrive download chain is missing the final hop in traces because the mock drive server has no OTel instrumentation.

**Solution:** Add trace context propagation to `tests/docker/mock_drive_server.py`:
- Call `setup_tracing()` at startup with `OTEL_SERVICE_NAME=GDrive`
- In `do_GET` handler: extract `traceparent` header via `TraceContextTextMapPropagator`, create a child span named `GET {slug}.pdf`
- The span appears in traces as `GDrive` service, linked to the Railway download span

**Files:** `tests/docker/mock_drive_server.py`, `tests/docker/start_hermetic.sh` (set `OTEL_SERVICE_NAME`)

## Change 2: Merge Initial Location into POST /register

**Problem:** Every participant join generates a separate `POST /api/participant/location` call immediately after registration. This is noise — the location is always available at registration time (timezone fallback or stored GPS).

**Solution:**
- **Daemon:** Add `location: str | None = None` to `RegisterRequest`. If provided, store and resolve it (reuse `_resolve_location_metadata` logic). No separate `/location` call needed for initial join.
- **JS:** In `_registerRailway()`, compute `storedLocation || getTimezoneLocation()` and include as `location` in the register POST body. Remove the `sendLocation()` call from `ws.onopen`.
- **Keep** `PUT /location` for explicit GPS permission grants and location updates after initial join.

**Files:** `daemon/participant/router.py` (RegisterRequest model + handler), `static/participant.js` (_registerRailway + ws.onopen), `static/utils.js` (if participantApi needs adjustment)

## Change 3: POST → PUT for /location

**Problem:** Updating a participant's location is idempotent — PUT is the correct HTTP verb.

**Solution:**
- Change route decorator from `@router.post` to `@router.put` for the `/location` endpoint
- Update `participant.js` to use PUT method for the `requestLocation` GPS success callback
- Update OpenAPI spec snapshot and contract tests

**Files:** `daemon/participant/router.py`, `static/participant.js`, `docs/openapi.yaml`, contract test snapshots

## Impact on Sequence Diagrams

Before: `Participant -> Daemon: POST /api/participant/location` appears as a separate gray arrow in every scenario's Given phase.

After: Location is embedded in the register call. The separate arrow disappears. GDrive appears as a new actor in the slides check flow.

## Testing

- Existing hermetic BDD tests verify participant join still works
- Unit tests for register endpoint verify location is stored when provided
- Contract tests updated for PUT /location and new RegisterRequest field
- Regenerate extracted sequence diagrams to verify GDrive actor appears
