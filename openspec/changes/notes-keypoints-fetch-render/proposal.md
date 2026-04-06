## Why

Participant and host UIs have notes/key-points buttons and badges, but clicking them doesn't fetch fresh content from the daemon REST API. The host side also lacks proper WS-driven enable/disable behavior and content modals that the participant side already has. This gaps means users can't actually read notes or key points from the UI.

## What Changes

- Participant: clicking "Notes" or "Key Points" buttons fires GET requests to the daemon API (`/api/participant/notes`, `/api/participant/summary`) and renders content in modals (markdown for key points, plain text with clickable links for notes)
- Host: clicking notes/summary badges fires GET requests to daemon API (`/api/{sid}/host/notes`, `/api/{sid}/host/summary`) and renders content in modals
- Host: properly handle `notes_updated` and `summary_updated` WS messages to enable/disable badges (same pattern as participant buttons)
- Both: links in content are rendered as clickable hyperlinks

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `notes_summary`: Add REST-based content fetching on button/badge click for both participant and host; add enable/disable behavior for host badges driven by WS count messages

## Impact

- `static/participant.js` — modal open handlers need to fetch from daemon REST API
- `static/host.js` — badge click handlers, modal UI, WS message handling for enable/disable
- `static/host.html` — modal markup for notes and summary display
- No backend/daemon changes needed (endpoints and WS messages already implemented)
