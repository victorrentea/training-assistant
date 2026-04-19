# Share Location — Menu Entry (instead of Activity-pane button)

**Date:** 2026-04-19
**Scope:** Participant UI

## Motivation

Today, "Share my location" lives as a call-to-action inside the Activity pane. Moving it to the sidebar menu frees the Activity pane for its real content (poll, welcome, waiting state) and gives location sharing a persistent, discoverable home.

## Behavior

- **New entry:** Add "Share my location" to the participant sidebar nav, positioned **last** (after "Upload / Paste"), using the `location_on` Material icon.
- **Removed:** Delete the `activity-location-section` block (prompt copy + button) from inside `activity-view`.
- **Visibility rules:**
  - Hidden if `navigator.geolocation` is unsupported.
  - Hidden if permission state is `granted` (auto-send silently on page load, as today).
  - Visible in all other cases (`prompt`, `denied`, or when the Permissions API is unavailable).
- **Click flow:**
  1. Browser geolocation is requested.
  2. On success, `PUT /api/participant/location` is called.
  3. On HTTP 204 (daemon confirmed), the menu entry is hidden.
  4. On any failure (permission denied, geolocation error, network/HTTP error), the menu entry stays visible so the user can retry.
- **Guard:** Once a successful PUT lands in the current page session, `_activityLocationSent` is set to `true` and no further sends happen.

## Non-goals

- No persistence across reloads — browser permission state is already the source of truth. On reload with `granted`, we re-send silently; with `prompt`/`denied`, the entry re-appears.
- No user-visible error message on failure; silent retry path via the menu entry.

## Affected files

- `static/participant.html` — nav markup (new entry), `activity-view` markup (removed section), `initActivityView` / `requestParticipantLocation` / `_sendParticipantLocation` JS.
