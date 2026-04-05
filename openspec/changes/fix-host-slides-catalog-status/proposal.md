## Why

The host footer badge for slides catalog currently shows an empty list even when the backend has catalog entries and cache status from Railway. This regressed after Railway proxying and blocks the host from validating slide availability during live sessions.

## What Changes

- Restore host-side slides catalog population so the footer badge shows the same catalog and cache status data available to participants.
- Align host data loading with the existing participant `get-api-slides` path to avoid duplicate data-fetching logic.
- Change `/api/slides` response shape so each slide entry embeds cache status directly (`slides[].status`) instead of a separate `cache_status` map.
- Keep current host UI behavior and visuals, but ensure the badge list is populated from real backend data.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `slides`: Host UI must correctly load and display slide catalog entries with Railway cache status in the footer badge.

## Impact

- Affected frontend files in `static/` (host slides data fetching and rendering path).
- Affected slides API contract and async docs for cache-status updates.
- Verifies compatibility with Railway-proxied data flow.
