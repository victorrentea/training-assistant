## Context

Slides are served through a split architecture: daemon tracks freshness and orchestrates download intent, while Railway stores and serves PDF binaries to participants. The daemon already exposes `GET /{sid}/api/slides/check/{slug}` to gate readiness, but participant JavaScript still fetches the PDF directly, bypassing this gate. During live sessions this causes participant fetches to race ahead of backend preparation.

## Goals / Non-Goals

**Goals:**
- Enforce a deterministic participant flow: `check` first, PDF download second.
- Preserve low-latency behavior when PDF is already cached.
- Provide stable participant behavior during cache-miss or stale-pdf refresh windows.

**Non-Goals:**
- Redesign daemon cache lifecycle or GDrive fingerprint logic.
- Add new backend services or storage layers.
- Change host-side slide control UX.

## Decisions

1. Participant-side check gate is mandatory before PDF fetch.
Rationale: The daemon is the source of truth for PDF readiness and download triggering. Making `check` mandatory eliminates client-side races and aligns with existing daemon contract.
Alternative considered: keep optimistic direct PDF fetch with fallback to `check`. Rejected because it still produces avoidable 404/503 churn and duplicate client retries.

2. Keep endpoint responsibilities unchanged.
Rationale: `check` remains readiness and trigger endpoint; Railway remains binary-serving endpoint. This avoids backend refactors and limits change scope to integration behavior.
Alternative considered: serve PDF through daemon directly. Rejected due to explicit project constraint that daemon must not proxy large files.

3. Participant retry/wait behavior is explicit on non-200 check outcomes.
Rationale: Users need predictable feedback when a slide is being prepared. UI should avoid silent failures and repeated blind PDF fetches.
Alternative considered: immediate hard failure. Rejected because preparation can complete shortly after and a guided retry provides better live-session resilience.

## Risks / Trade-offs

- [Risk] Added pre-download HTTP roundtrip may slightly increase perceived load time.
  Mitigation: Fast-path `check` returns immediately when cached; reuse existing retry cadence only on transient unavailability.

- [Risk] If check and download URLs diverge by slug/session handling, users can still fail after passing check.
  Mitigation: Keep both requests built from the same normalized slug/session source in participant JS.

- [Risk] Existing tests may not assert call ordering.
  Mitigation: Add/adjust tests to verify no PDF download request is issued before successful `check`.

## Migration Plan

- Update participant slide-loading code path to call `check` first.
- Validate behavior for cached, in-progress, and timeout/error states.
- Deploy with no data migration; rollback is a frontend revert.

## Open Questions

- Should participant auto-retry `check` with backoff or require explicit user retry in all failure states?
- Should UI copy distinguish daemon timeout (`503`) from generic network failures?
