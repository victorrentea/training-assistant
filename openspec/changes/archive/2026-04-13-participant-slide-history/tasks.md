## 1. Daemon — Pydantic Response Model

- [x] 1.1 Add `SlideHistoryResponse(BaseModel)` with `slides: list[ViewedSlide]` to `daemon/participant/models.py` (or the appropriate models file in the participant package)

## 2. Daemon — New Endpoint

- [x] 2.1 Add `GET /slide-history` route to `daemon/participant/router.py` that reads `persisted_state.slides_viewed` and returns a `SlideHistoryResponse`
- [x] 2.2 Verify the route is registered under the `/api/participant` prefix in `daemon/host_server.py`

## 3. API Contract

- [x] 3.1 Regenerate `API.md` via `python3 scripts/generate_apis_md.py --output API.md` and verify the new endpoint appears

## 4. Participant UI

- [x] 4.1 In `static/participant.html`, add a `<div id="slide-history-list">` container below the current slide area in the slides dock (hidden by default)
- [x] 4.2 In `static/participant.js`, on slides-item click: call `GET /api/participant/slide-history`, render `file_name + page` entries inside `#slide-history-list`, and start a `setTimeout(hideList, 30000)`
- [x] 4.3 On a second click while list is visible or collapsed: clear any running timer, re-fetch, re-render, restart the 30-second timer
- [x] 4.4 If response `slides` is empty, leave `#slide-history-list` hidden (still start and clear the timer)

## 5. Verification

- [ ] 5.1 Start the daemon locally and call `GET http://localhost:8081/api/participant/slide-history` — confirm `{"slides": []}` when no slides have been viewed
- [ ] 5.2 Open participant page in browser, click the slides item, confirm history list appears and disappears after 30 s
- [ ] 5.3 Click again — confirm list re-fetches and timer resets
