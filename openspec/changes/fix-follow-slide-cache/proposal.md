## Why

When a participant clicks Follow and the host's current slide is not yet cached on Railway, they see nothing — the slide fails to load silently. The root cause is that Railway's `proxy_to_daemon` has a 5-second timeout, while the daemon's `/api/slides/check/{slug}` waits up to 30s for a PDF download to complete. The Follow experience must be seamless: click → slide appears at the host's current page, no matter the cache state.

## What Changes

- **Railway proxy_bridge**: Add optional `timeout` parameter to `proxy_to_daemon`; slides check uses 35s instead of 5s.
- **Client `_checkSlideReady`**: Show a "Downloading slide..." loading message while the long-running check call is in progress (not just "Checking cache...").
- **Client `_loadSlideIntoViewer`**: On check failure during follow mode, do not show a permanent error — instead queue a retry follow attempt once cache status updates (via `slides_cache_status` WS event).
- **Hermetic E2E test**: New test verifying the full uncached Follow path — participant clicks Follow, slide is not cached, download is triggered, PDF appears at the correct host page.

## Capabilities

### New Capabilities
- `follow-uncached-slide`: Participant Follow button seamlessly loads a slide that is not yet cached on Railway, waiting for the download to complete before rendering the PDF at the host's current page.

### Modified Capabilities
- `slides`: The Railway slides check proxy now supports long-running requests (up to 35s); client loading state during check is more descriptive.

## Impact

- `railway/features/ws/proxy_bridge.py`: Add `timeout` param to `proxy_to_daemon`
- `railway/features/slides/router.py`: Pass `timeout=35.0` for slides check call
- `static/participant.js`: Improve loading label during `_checkSlideReady`; improve error handling in follow mode (retry instead of permanent error)
- `tests/docker/`: New hermetic test `test_follow_uncached_slide.py`
