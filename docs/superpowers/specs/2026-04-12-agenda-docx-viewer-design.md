# Agenda .docx Viewer — Design Spec

## Overview

Participants can view an agenda document (`.docx`) from the session folder, rendered in-browser via mammoth.js. The daemon detects the file at session start and signals its availability; the frontend shows a Word icon in the status bar that opens a read-only modal.

## Daemon

### File Detection

- On session start (when the session folder is resolved), scan for `.docx` files in the session folder root.
- Prefer `agenda.docx` if present; otherwise pick the first `.docx` found alphabetically.
- Store the resolved path in session state (e.g. `agenda_docx_path: Path | None`).
- Re-scan when the session changes.

### State Signal

- Add `has_agenda: bool` to the `state` WS message payload sent to participants.
- `True` when a `.docx` file was found in the current session folder, `False` otherwise.

### REST Endpoint

- `GET /api/participant/agenda` — serves the raw `.docx` bytes.
- Content-Type: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.
- Returns 404 if no agenda file is available.
- No authentication required (participant endpoint).

### Railway Proxy

- Add `/api/participant/agenda` to the Railway proxy pass-through list so it reaches the daemon.

## Frontend

### CDN Library

Add to `participant.html` head:

```html
<script src="https://cdn.jsdelivr.net/npm/mammoth@1/mammoth.browser.min.js"></script>
```

### Status Bar Button

- New button in `.status-right`, positioned before the Notes button.
- Hidden by default (`style="display:none"`).
- Shown/hidden based on `has_agenda` in the `state` WS message.
- Uses an inline SVG Word/document icon styled consistently with existing `.header-link-btn` buttons.
- Label: "Agenda" (no emoji — uses SVG icon).

### Modal Dialog

- Follows the existing Notes/Summary modal pattern: `.modal-overlay` + `.modal-dialog`.
- Header: document icon + "Agenda" title + close button (✕).
- Body: scrollable container with the mammoth-rendered HTML.
- Basic styling for rendered content (headings, lists, tables, paragraphs) scoped under `.agenda-content`.

### Behavior

- `toggleAgendaModal()`: if not yet fetched, fetch `/api/participant/agenda` as ArrayBuffer, convert with `mammoth.convertToHtml()`, cache the HTML. Toggle the modal overlay.
- Cache is cleared on session change (when a new `state` message arrives with different session info).
- On fetch/render error, show a brief error message in the modal body.

## Out of Scope

- No host-side controls for agenda management.
- No `.doc` (legacy binary format) support.
- No print, zoom, or search within the modal.
- No editing capabilities.
