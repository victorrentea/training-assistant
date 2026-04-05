## Context

The participant UI already fetches slides and cache status through the Railway-proxied slides API (`get-api-slides` path), while the host footer badge currently renders an empty catalog after the proxying refactor. The regression indicates host-side data initialization is not aligned with the participant data path, even though both surfaces need the same catalog and cache payload.

## Goals / Non-Goals

**Goals:**
- Make host slides badge load catalog and cache status from the same API path used by participants.
- Restore non-empty host catalog rendering when daemon-backed slides data exists.
- Preserve existing host footer UI and interaction model.

**Non-Goals:**
- No redesign of host footer badge.
- No changes to slide cache semantics or daemon catalog source.

## Decisions

1. Reuse participant API helper for host slide fetch path.
- Rationale: Single client-side retrieval contract reduces divergence and prevents proxy-specific regressions.
- Alternative considered: Keep separate host fetch logic and patch endpoint/shape handling. Rejected because it duplicates logic and likely reintroduces drift.

2. Normalize host state update from API payload before rendering badge list.
- Rationale: Host rendering should consume the same `slides[]` structure (with embedded `status`) as participant flow.
- Alternative considered: Render directly from raw response in each host UI function. Rejected because it spreads parsing and makes empty-state bugs harder to prevent.

3. Normalize Railway `/api/slides` proxy response to embed cache status in each slide entry.
- Rationale: A single `slides[]` contract removes cross-field joins and keeps host/participant parsing simple and aligned.
- Alternative considered: Keep `cache_status` as separate map and require clients to merge. Rejected due repeated UI merge logic and empty-list regressions.

4. Trigger host fetch on startup/reconnect at the same lifecycle moment used for participant refresh.
- Rationale: Ensures host has fresh catalog data after Railway restart, daemon reconnect, or page reload.
- Alternative considered: Depend only on push updates. Rejected because push may not include full initial catalog state.

## Risks / Trade-offs

- [Shared helper coupling] Host flow becomes coupled to participant helper contract -> Mitigation: keep helper output stable and add focused regression tests for both host and participant consumers.
- [Transient empty states during reconnect] Host may briefly show empty while fetch is in flight -> Mitigation: keep existing loading/empty handling and only replace state on successful parse.
- [API shape drift] If backend payload changes, both UIs can break simultaneously -> Mitigation: validate response shape in one normalization point and fail loudly in logs.

## Migration Plan

- Implement host fetch path switch to shared slides API helper.
- Verify host footer badge shows catalog entries and cache status locally with daemon-backed data.
- Rollout via normal deploy; rollback is reverting host fetch wiring commit.

## Open Questions

- None.
