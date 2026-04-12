## Context

The daemon accumulates per-slide viewing durations in `persisted_state.slides_viewed: list[ViewedSlide]` (defined in `daemon/persisted_models.py`). Data arrives from the trainer's addons via the existing addon→daemon pipeline (`daemon/slides/merge_viewed.py`). This data is currently used only internally (e.g., to display in RAG or host views) and is never exposed to participants.

Railway already transparently proxies all `GET /api/participant/*` calls to the daemon, so no Railway-side changes are required. The daemon's participant router lives in `daemon/participant/router.py`.

## Goals / Non-Goals

**Goals:**
- Add `GET /api/participant/slide-history` to the daemon's participant router.
- Return the full `slides_viewed` list from the current persisted session state.
- Use a proper Pydantic response model.

**Non-Goals:**
- Modifying how `slides_viewed` is populated (addon pipeline is out of scope).
- Filtering or paginating the list (all records are returned; the list is small — one entry per unique slide shown).
- Authentication / per-participant filtering (all participants see the same slide history for the session).

## Decisions

### D1: Route location — `daemon/participant/router.py`
The endpoint is participant-facing and read-only. Placing it alongside the other `/api/participant/` routes in `daemon/participant/router.py` keeps the grouping clean. Alternative: `daemon/misc/router.py` — rejected because misc mixes unrelated concerns.

### D2: Response model — new `SlideHistoryResponse` wrapping existing `ViewedSlide`
`ViewedSlide` (from `persisted_models.py`) already has the right fields. We wrap it in a new `SlideHistoryResponse(BaseModel)` with a single field `slides: list[ViewedSlide]` to allow future envelope additions (e.g., `last_updated`) without breaking clients.

### D3: Data source — `persisted_state.slides_viewed`
The persisted state is the source of truth for accumulated viewing durations across the session. The in-memory `misc_state.slides_viewed` (a list of dicts) is an intermediate buffer — using the typed persisted list is safer and avoids duplication.

### D4: UI interaction — click-to-expand, 30-second auto-collapse
When a participant clicks the slides item in the slides dock, `GET /api/participant/slide-history` is called immediately. The result is rendered as a list below the current slide view. A `setTimeout` of 30 000 ms clears the list. A second click re-fetches and re-expands (resetting the timer). No persistent local state is kept — each expand always fetches fresh data. Alternative: cache the last response client-side — rejected to keep implementation simple and ensure data is always current.

### D5: Empty-list handling
If the endpoint returns `{"slides": []}`, the list area is not rendered (no empty placeholder shown). The auto-collapse timer is still started, but there is nothing to clear.

## Risks / Trade-offs

- **Stale data if daemon restarts mid-session** → Mitigated: `slides_viewed` is in persisted state, so it survives daemon restarts.
- **All participants see the trainer's slide history, not their own individual history** → Accepted: the current model tracks what the trainer showed, not what each participant chose to view. This is the intended semantics.
- **Empty list before any slides are shown** → Expected and documented in specs; clients must handle an empty list gracefully.
