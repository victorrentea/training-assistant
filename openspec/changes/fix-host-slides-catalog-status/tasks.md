## 1. Host Slides Data Loading

- [ ] 1.1 Identify the host footer slides badge data path and remove/replace the fetch logic that leaves catalog empty after Railway proxying.
- [ ] 1.2 Wire host slides initialization to the same `GET /api/slides` retrieval helper used by participants (`get-api-slides` flow).
- [ ] 1.3 Normalize host state assignment from `slides[]` entries with embedded `status` before rendering.

## 2. API Shape + Host Rendering and Reconnect Behavior

- [ ] 2.1 Update Railway `/api/slides` response shaping so cache status is embedded per slide entry (no separate `cache_status` contract for clients).
- [ ] 2.2 Update host footer badge rendering to consume normalized slides catalog entries and show per-slide cache status.
- [ ] 2.3 Trigger host slides re-fetch on WebSocket reconnect so catalog repopulates after Railway restarts.
- [ ] 2.4 Keep current host UI structure/styling unchanged while fixing data population.

## 3. Verification

- [ ] 3.1 Add or update frontend tests (or equivalent targeted checks) proving host badge list is populated when `GET /api/slides` returns data.
- [ ] 3.2 Verify participant flow still works with the shared helper path and no regression in slide list/cache indicators.
- [ ] 3.3 Run project verification commands and capture evidence for the fix.
