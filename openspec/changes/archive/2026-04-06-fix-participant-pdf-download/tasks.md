## 1. Daemon Check/Download Consistency

- [x] 1.1 Update `daemon/slides/router.py` so `/check` returns immediate 200 only when Railway download availability is confirmed for that slug.
- [x] 1.2 Keep/trigger `download_pdf` handshake when Railway availability is not confirmed, even if daemon-local status is `cached`.
- [x] 1.3 Ensure timeout/error paths keep `slides_cache_status` accurate and debuggable.

## 2. Participant Download Flow

- [x] 2.1 Update slide-list download click handling in `static/participant.js` to call `/api/slides/check/{slug}` before navigating to download.
- [x] 2.2 Preserve expected UX/accessibility behavior (download icon remains clickable and does not open slide viewer).
- [x] 2.3 Show clear retry messaging when readiness check fails for user-triggered download.

## 3. Regression Coverage and Verification

- [x] 3.1 Add tests that cover the mismatch regression (`/check` 200 followed by `/download` 404) and verify it no longer occurs.
- [x] 3.2 Add/adjust participant-flow test coverage for list-download readiness gating.
- [ ] 3.3 Validate manually on production-like session flow and capture evidence for completion notes.
