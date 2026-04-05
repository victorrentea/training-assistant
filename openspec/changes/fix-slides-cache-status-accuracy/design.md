## Context

Slides cache state is currently inconsistent with real Railway PDF availability. At startup, daemon can mark slides as cached based on local daemon-side publish files, while participant downloads still block on `/check`, proving the file is not actually available on Railway. During active downloads, participants can stay stuck in loading state because cache-complete transitions are not consistently propagated/merged into client state.

## Goals / Non-Goals

**Goals:**
- Make startup cache status truthfully represent Railway-side PDF availability.
- Ensure `pdf_download_complete` transitions update daemon cache state and are broadcast so participant and host UIs move from loading to cached.
- Keep one consistent cache-state contract in `/api/slides` and WS refresh events.

**Non-Goals:**
- No new activity or slide-viewer UX.
- No changes to the mandatory `/check` gating flow before PDF download.
- No new storage backend or persistence model.

## Decisions

1. Railway availability is authoritative for cache-ready semantics.
- Rationale: users consume PDFs from Railway, so cached status must reflect Railway disk, not local daemon publish artifacts.
- Alternative considered: infer cached from daemon local publish dir. Rejected because it creates false-green status.

2. Daemon SHALL persist status transitions from download completion and rebroadcast immediately.
- Rationale: once Railway reports `pdf_download_complete`, daemon is source-of-truth for status fan-out to both participant and host.
- Alternative considered: rely on ad-hoc UI refresh polling only. Rejected due delayed/stuck loading indicators.

3. Clients refresh catalog on slide update trigger and merge status updates by slug deterministically.
- Rationale: ensures both initial and incremental status changes converge even across reconnects.
- Alternative considered: only local in-memory update without catalog refresh. Rejected due drift risk after reconnect/reload.

## Risks / Trade-offs

- [Startup Railway probe latency] Verifying Railway availability may add startup cost -> Mitigation: bounded timeout and fallback to `not_cached` on probe failure.
- [Transient mismatch during download] UI might briefly show downloading while backend settles -> Mitigation: always emit `slides_cache_status` on status change and re-fetch on `slides_updated`.
- [Event ordering issues] WS events may arrive out of order -> Mitigation: status merge keyed by slug and idempotent updates.

## Migration Plan

- Update daemon startup status initialization logic to avoid local-file-based cached assumptions.
- Harden `pdf_download_complete` handling and status broadcast path.
- Update participant/host status refresh handling and add regression coverage.
- Deploy normally; rollback is reverting the change if unexpected regressions occur.

## Open Questions

- None.
