## Why

Participants have no visibility into which slides they were shown during a session. The daemon already accumulates per-slide viewing durations (from addons) in persisted state, but this data is never exposed to participants — making it impossible to build a "slides I've seen" history in the participant UI.

## What Changes

- New `GET /api/participant/slide-history` endpoint in the daemon that returns the accumulated `slides_viewed` list for the current session.
- The Railway proxy already forwards all `/api/participant/*` calls to the daemon, so no Railway changes are needed.
- The participant UI gains a slide history drop-down in the slides dock: clicking the slides item fetches `/slide-history`, renders the list below the current slide view, then auto-collapses after 30 seconds. Clicking again re-expands it.

## Capabilities

### New Capabilities

- `participant-slide-history`: Expose `GET /api/participant/slide-history` returning the list of `ViewedSlide` records (file_name, page, seconds) accumulated by the daemon from addon activity, and render it as a collapsible history list in the participant slides dock.

### Modified Capabilities

_(none — `slides_viewed` population via addons is unchanged; this change only adds a read endpoint and UI interaction)_

## Impact

- **Daemon**: New route added to `daemon/participant/router.py`.
- **Pydantic models**: New response model `SlideHistoryResponse` wrapping `list[ViewedSlide]`.
- **Railway**: No changes needed — `/api/participant/slide-history` is auto-proxied.
- **Participant UI** (`static/participant.html` / `static/participant.js`): History list rendered below current slide; auto-collapses after 30 s; toggle on click.
- **API.md**: Must be regenerated after adding the new endpoint.
