## 1. Startup Cache Status Accuracy

- [x] 1.1 Replace daemon startup cache initialization logic that infers `cached` from local publish files.
- [x] 1.2 Initialize each catalog slug to Railway-availability-based status (`cached` only when Railway confirms file presence; otherwise `not_cached`).
- [x] 1.3 Ensure `/api/slides` payload uses embedded per-slide status from that corrected source-of-truth.

## 2. Download Completion and Status Propagation

- [x] 2.1 Harden `/check` flow so a stale false-`cached` state is downgraded and triggers `download_pdf` instead of returning immediate success.
- [x] 2.2 Ensure daemon handles `pdf_download_complete` by persisting status transition (`cached`/`download_failed`) for the slug.
- [x] 2.3 Broadcast `slides_cache_status` updates to both participant and host so loading indicators transition to final state.

## 3. Frontend Status Convergence

- [x] 3.1 Verify participant slide list status merge logic replaces spinner/loading with green dot when `cached` update arrives.
- [x] 3.2 Verify host slide status UI consumes the same update path and shows consistent per-slide status.
- [x] 3.3 Keep single refresh trigger/event behavior and avoid divergent cache-state paths between host and participant.

## 4. Verification

- [x] 4.1 Add/update daemon unit tests for startup status accuracy and `/check` downgrade-from-false-cached behavior.
- [x] 4.2 Add/update integration tests for `pdf_download_complete` -> broadcast -> client-visible status transition.
- [x] 4.3 Run targeted slides + contract checks and capture proof.
