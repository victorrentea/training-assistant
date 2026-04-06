## Context

The Follow button lets participants auto-sync to the host's current slide. When a participant joins mid-session and clicks Follow, the host's slide may not yet be cached on Railway (no participant has opened it yet). The flow is:

1. Participant clicks Follow → `_applyHostSlideFollow` → `_loadSlideIntoViewer` → `_checkSlideReady(checkUrl)`
2. `_checkSlideReady` calls `GET /api/slides/check/{slug}` on Railway
3. Railway proxies to daemon via `proxy_to_daemon` — **which has a hardcoded 5-second timeout**
4. The daemon's check endpoint waits up to 30s for Railway to download the PDF from Google Drive
5. After 5s, Railway proxy times out → returns 503
6. `_loadSlideIntoViewer` catches the error and shows "Slide is still preparing" — the participant sees a dead-end error instead of the slide

The daemon architecture is correct — `check` already orchestrates the download and holds the connection open. The only gap is the Railway proxy timeout being too short.

## Goals / Non-Goals

**Goals:**
- Participant Follow works seamlessly even when the slide is not yet cached
- Loading state is informative (not just silent spinner)
- Hermetic E2E test coverage for the uncached follow scenario

**Non-Goals:**
- Proactive slide pre-warming on daemon startup (explicitly excluded by existing spec)
- Changing the WS-based download orchestration between daemon and Railway
- Supporting offline/daemon-disconnected scenarios

## Decisions

### Decision 1: Extend proxy timeout for slides check only (chosen)

Add an optional `timeout` parameter to `proxy_to_daemon`. The slides check endpoint passes `timeout=35.0` (5s more than daemon's 30s check wait).

**Why not a global timeout increase?**
The 5s timeout is correct for all other proxy calls (API calls that should be fast). Only the slides check legitimately needs to wait for a download.

**Why not client-side polling?**
Polling would require changing the daemon check contract (return 202 with status, not block-and-return-200). That's a bigger change with more moving parts. The current blocking-check architecture is simpler and already correct — we just need to let it breathe.

**Alternative: SSE/WS push for download completion**
The participant already receives `slides_cache_status` WS events when a download finishes. We could use that to retry. However, if the participant clicks Follow *after* the download is triggered by another participant, the cache status WS event may already have fired. The polling approach would also miss this. The extended timeout covers all cases cleanly.

### Decision 2: Improve UX during long check — show "Downloading slide..." label

When a check call takes more than ~1s (i.e., a download is in progress), the loading label should update to "Downloading slide..." to reassure the participant. This is a cosmetic improvement showing descriptive progress.

**Implementation:** Start with "Preparing slide..." label. After 1.5s, if still waiting, switch label to "Downloading slide from trainer's library…".

### Decision 3: On check failure during follow mode, queue retry on next cache status event

If the check still fails (e.g., download takes >30s on daemon side, or network error), the participant currently sees a permanent error. In follow mode, the right behavior is to auto-retry when the `slides_cache_status` WS event arrives (indicating the download eventually completed).

**Implementation:** In `_loadSlideIntoViewer`, when called from follow mode and check fails, set a `_pendingFollowRetry` flag. In the `slides_cache_status` handler, if flag is set, re-queue the follow.

## Risks / Trade-offs

- **35s open HTTP connection through Railway**: Railway (FastAPI + uvicorn) handles concurrent async requests fine. A 35s long-poll is a standard pattern. Risk: low.
- **Retry on WS event fires prematurely**: The `slides_cache_status` event fires for any slug download, not necessarily the one the participant is waiting for. The retry path calls `_queueHostSlideCurrent()` which re-evaluates the check — if it still fails, no visual change. Acceptable.
- **withUiBlocker=false on follow path**: Follow calls `_loadSlideIntoViewer` without the full-screen blocker. The loading spinner is still shown via `_setSlidesLoading`. No change needed here.
