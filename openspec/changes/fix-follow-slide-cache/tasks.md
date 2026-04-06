## 1. Fix Railway proxy timeout for slides check

- [x] 1.1 Add optional `timeout: float = PROXY_TIMEOUT` parameter to `proxy_to_daemon` in `railway/features/ws/proxy_bridge.py`
- [x] 1.2 In `railway/features/slides/router.py`, pass `timeout=35.0` to the `proxy_to_daemon` call in `check_slide`
- [x] 1.3 Verify existing unit tests for proxy_bridge still pass (`bash tests/check-all.sh`)

## 2. Improve participant loading UX during slide check

- [x] 2.1 In `static/participant.js`, in `_loadSlideIntoViewer`, start a timer after `_setSlidesLoading({label:'Preparing slide...'})` that updates the label to `'Downloading slide from trainer's library…'` after 1500ms if the check hasn't resolved yet; clear the timer on resolve or reject
- [x] 2.2 Extract a helper `_checkSlideReadyWithProgressLabel(checkUrl, setLabelFn)` or inline the timer logic cleanly inside `_loadSlideIntoViewer`

## 3. Auto-retry follow on cache status event after check failure

- [x] 3.1 Add a module-level flag `_pendingFollowRetry = false` in `static/participant.js`
- [x] 3.2 In `_loadSlideIntoViewer`, when the check throws and `_isSlidesFollowActive()` is true, set `_pendingFollowRetry = true` instead of returning a permanent error
- [x] 3.3 In the `slides_cache_status` WS handler (currently calls `_refreshSlidesCatalog()`), after refresh, if `_pendingFollowRetry` is true, clear it and call `_queueHostSlideCurrent()`
- [x] 3.4 Clear `_pendingFollowRetry` when follow mode is disabled (`_setSlidesFollowTrainerEnabled(false, ...)`)

## 4. Hermetic E2E test — uncached Follow

- [x] 4.1 Create `tests/docker/test_follow_uncached_slide.py` with a test `test_follow_opens_uncached_slide`:
  - Use the mock Google Drive fixture (8s delay — exceeds old 5s proxy timeout, fits new 35s)
  - Set `slides_current` via `activity-slides-*.md` file (same as `test_follow_me.py`)
  - Fresh session guarantees slide not cached
  - Participant joins, follow mode on by default, daemon sends `slides_current`
  - Assert: overlay opens, correct slide active, correct page, follow still ON
- [x] 4.2 Add `test_follow_retries_after_cache_status_event` (covers daemon-timeout retry path):
  - 32s Drive delay → daemon /check returns 503 → `_pendingFollowRetry = true`
  - Remove delay after 5s → Railway finishes background download
  - Daemon broadcasts `slides_cache_status` → participant auto-retries → slide loads
- [x] 4.3 Run hermetic tests locally: `bash tests/docker/run-hermetic.sh` — confirm all pass
- [x] 4.4 Both tests tagged `@pytest.mark.nightly` (each takes ~20-60s)

## 5. Commit, push, and verify deploy

- [ ] 5.1 Run full test suite: `bash tests/check-all.sh`
- [ ] 5.2 Commit all changes with a descriptive message
- [ ] 5.3 Push to master and wait for Railway deploy using `wait-for-deploy` skill
- [ ] 5.4 Manually verify: open two browser tabs (host + participant), set a slide as current, open participant in incognito, click Follow — confirm slide loads seamlessly
