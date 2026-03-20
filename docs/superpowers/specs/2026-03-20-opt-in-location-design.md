# Opt-in Location Sharing (Item 120)

## Problem

The participant UI currently triggers the browser geolocation permission prompt automatically on connect. This can feel invasive — participants may worry about being tracked, especially if they're not where they're expected to be.

## Design

### Participant UI Changes

**"Where are you?" prompt in top bar:**
- Displayed only when no location is stored in `localStorage`
- Clickable text/link, inviting style — not a button
- On click: triggers `navigator.geolocation.getCurrentPosition()`
- On success: store GPS coordinates in `localStorage` (key: `workshop_participant_location`), send via WebSocket, hide the prompt
- On geolocation denial: prompt remains visible (user can retry later)
- On reconnect/refresh with stored location: send automatically via WebSocket — no browser prompt, no UI prompt

**Timezone fallback (silent, always sent):**
- On every WebSocket connect, send IANA timezone string (e.g. `Europe/Bucharest`) — this requires no browser permission
- If stored GPS location exists in localStorage, send that instead (overrides timezone)

### Server Changes

Minimal. The server already accepts `location` WebSocket messages with either GPS coords or timezone strings. No protocol changes needed.

### Host UI Changes

None. The host already handles both GPS coordinates (lazy-resolved via Nominatim) and timezone strings.

### What Gets Removed

- Automatic `navigator.geolocation.getCurrentPosition()` call in `resolveLocation()` on WebSocket open
- The current `resolveLocation()` function is replaced by two separate paths: silent timezone send + explicit user-triggered GPS collection

### localStorage Key

- `workshop_participant_location` — stores the raw `"lat, lon"` string once collected
- Persists indefinitely (across browser restarts, sessions, days)

### Edge Cases

- Participant clears browser data → "Where are you?" reappears, timezone sent as fallback
- Participant uses "Leave" button → location stays in localStorage (it's a browser-level preference, not a session-level one)
- Server restart → locations re-sent on reconnect from localStorage or timezone fallback
