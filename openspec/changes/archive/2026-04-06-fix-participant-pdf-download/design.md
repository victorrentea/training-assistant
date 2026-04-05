## Context

Slides readiness is split between daemon and Railway. The daemon currently marks slugs as `cached` using local daemon-side signals, while participants download from Railway (`/{sid}/api/slides/download/{slug}`). In production, this allows a false-positive path: daemon returns `200` on `/check`, but Railway still returns `404` for the same slug.

## Goals / Non-Goals

**Goals:**
- Ensure `/check` success is a reliable precondition for immediate Railway download success.
- Keep the existing daemon-driven orchestration model (`download_pdf` / `pdf_download_complete`).
- Make participant download clicks resilient by using the same gate as viewer loads.

**Non-Goals:**
- Redesigning the entire slides catalog format.
- Introducing persistent DB state for cache tracking.
- Changing host-side slide authoring or upload UX.

## Decisions

1. Validate Railway availability before returning immediate `/check` success.
Rationale: daemon-local `cached` status is not authoritative for Railway-serving state.
Alternative considered: trust local cache status and only fix participant UI; rejected because backend contract remains inconsistent and fragile for other clients.

2. Keep `download_pdf` as the single remediation path when readiness probe fails.
Rationale: preserves current responsibility split and minimizes architecture change.
Alternative considered: serving PDFs directly from daemon; rejected because it violates the project constraint that large-file downloads must happen on backend, not host machine.

3. Route participant list-download through readiness gating.
Rationale: users can click download without opening the slide viewer, so the click path must call `/check` before navigating to `/download`.
Alternative considered: keep raw anchor-only download; rejected due recurrent first-click 404 risk.

## Risks / Trade-offs

- Extra readiness probe on `/check` may add a small latency cost. -> Mitigation: use lightweight `HEAD`/existence checks and short timeouts.
- If Railway is temporarily unreachable, more checks may trigger re-download flows. -> Mitigation: preserve timeout/error states and user-visible retry messaging.
- UI click handler changes can regress keyboard/accessibility behavior. -> Mitigation: keep anchor semantics and add click-flow tests.

## Migration Plan

1. Ship daemon `/check` readiness validation and participant download gating together.
2. Verify in production with one session slug that used to fail (`/check=200` followed by `/download=404`).
3. Roll back by restoring previous `/check` fast-path if unexpected latency or availability regressions appear.

## Open Questions

- Should readiness use direct Railway `HEAD /api/slides/download/{slug}` probing or a shared in-memory Railway acknowledgment map synced by WS events?
- Do we want a dedicated `status: not_on_railway` value for clearer diagnostics in `slides_cache_status`?
