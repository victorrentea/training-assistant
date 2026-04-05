## 1. Participant Check-Then-Download Flow

- [x] 1.1 Locate the participant slide PDF load path in `static/participant.js` and route it through a dedicated `check`-before-download sequence.
- [x] 1.2 Add `GET /api/slides/check/{slug}` call before any `GET /api/slides/pdf/{slug}` request and block PDF fetch until check returns HTTP 200.
- [x] 1.3 Ensure non-200 check responses keep the slide in retry/wait state and do not trigger PDF download for that attempt.

## 2. Integration Consistency

- [x] 2.1 Reuse the same normalized slug/session source for both `check` and PDF endpoints to prevent mismatched URLs.
- [x] 2.2 Confirm existing WebSocket `slides_cache_status` handling clears retry/wait state after backend completion so user can retry successfully.

## 3. Verification

- [x] 3.1 Add or update tests to assert request ordering: no PDF request occurs before successful `check`.
- [x] 3.2 Validate cached, missing/stale, and timeout/error scenarios against the updated participant flow.
- [x] 3.3 Update `backlog.md` with the completed bug-fix entry once implementation is finished.
