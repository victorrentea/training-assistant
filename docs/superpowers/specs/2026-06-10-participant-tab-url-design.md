# Design: active tab reflected in the participant URL

**Date:** 2026-06-10
**Status:** Approved (design)
**Scope:** participant view (`static/participant.html`) + Railway page routing

## Goal

The participant view's address bar must always reflect the active tab, so a
tab-specific link can be pasted and shared. Example: while a participant is on
the Notes tab, the URL is `https://interact.victorrentea.ro/<session>/notes`.

Tabs (slugs) covered (decision: **all tabs**, not just the originally listed
five):

| Slug           | Source view                          |
| -------------- | ------------------------------------ |
| `slides`       | `slides-view` (default)              |
| `activity`     | `activity-view`                      |
| `notes`        | `notes-view`                         |
| `files`        | `files-view`                         |
| `summary`      | `summary-view`                       |
| `agenda`       | `agenda-view`                        |
| `upload-paste` | `upload-paste-view`                  |
| `feedback`     | `feedback-view`                      |
| `past-slides`  | slides view + Past Slides panel open |

The set mirrors the existing `VIEWS` array in `participant.html` plus the
special `past-slides` panel.

**Out of scope:** the nested-talk view (`static/talk.html`) has its own
`showView` with different tabs (`slides`, `speaker`); it is not modified. Deep
links to participant slugs on a talk session simply serve `talk.html`, which
ignores the slug and shows its default tab.

## Key constraint: the `/notes` collision

`/{session}/notes` is **already a real route** — it serves a *separate*,
actively-maintained, standalone read-only notes page (`static/notes.html`), not
the participant app. The other slugs (`/files`, `/slides`, ...) currently 404.

**Decision (approved):** path-based URLs (`/<session>/notes`, not
`/<session>/#notes`), and the participant app takes over `/notes`. The
standalone read-only notes page is **relocated** to `/<session>/notes-print`.

**Migration impact (accepted):** existing links to `/<session>/notes` now open
the participant app on its Notes tab instead of the bare read-only page. The
bare page remains available at `/<session>/notes-print`. `notes.html` derives
its session from `pathname.split('/')[1]`, which is unaffected by the new
suffix, so its `/api/notes` fetch keeps working.

## Backend design (`railway/features/pages/router.py`, `railway/app.py`)

The session-scoped participant router (`prefix="/{session_id}"`, registered last
as the catch-all, guarded by `require_valid_session`) currently defines only
`/` and `/notes`. Changes:

1. **Extract a helper** `_serve_participant_app()` that returns `talk.html` for
   talk sessions and `participant.html` otherwise (with OTel injection),
   removing duplication between `/` and the new tab route.

2. **Relocate the standalone notes page:** the route that serves
   `static/notes.html` moves from `/notes` to `/notes-print`.

3. **Add a single-segment tab route** `/{tab}` that serves the participant app.
   It validates `tab` against a known slug set:

   ```
   {slides, activity, summary, notes, agenda, feedback, upload-paste, files, past-slides}
   ```

   Unknown slugs raise `HTTPException(404)` so the catch-all cannot silently
   swallow arbitrary paths.

4. **Route ordering** within the participant router: `/`, then `/notes-print`,
   then `/{tab}` (literal routes beat the path param). The single-segment
   `/{tab}` cannot shadow the multi-segment `/api/...` participant sub-routers
   (different segment counts), so their registration order in `app.py` is safe.

### Route behavior matrix

| Request                       | Before            | After                          |
| ----------------------------- | ----------------- | ------------------------------ |
| `/<s>/`                       | participant app   | participant app (unchanged)    |
| `/<s>/notes`                  | notes.html        | participant app (Notes tab)    |
| `/<s>/notes-print`            | 404               | notes.html (read-only page)    |
| `/<s>/files` `/slides` etc.   | 404               | participant app (that tab)     |
| `/<s>/past-slides`            | 404               | participant app                |
| `/<s>/garbage`                | 404               | 404                            |
| `/<s>/api/...`                | proxied/handled   | unchanged                      |

## Frontend design (`static/participant.html`)

1. **One helper** `_setTabUrl(slug)`:

   ```js
   function _setTabUrl(slug) {
     if (!_sessionId || !slug) return;
     var p = '/' + _sessionId + '/' + slug;
     if (location.pathname !== p) history.replaceState(null, '', p);
   }
   ```

   **`replaceState`, not `pushState`** — switching tabs must not pile up browser
   history entries, and the mobile back-gesture should leave the page rather
   than "undo" a tab change.

2. **Write the URL** from:
   - `showView(name)` — the single chokepoint for main-view switches → `_setTabUrl(name)`.
   - `selectTopic(...)` — picking a slide implies the slides tab → `_setTabUrl('slides')`.
   - `togglePastSlides()` — open → `_setTabUrl('past-slides')`; close → revert to
     the current view's slug (`_setTabUrl(LS.getView())`).

3. **Read the URL on load** at the init block (`participant.html` ~line 2911,
   right before `var saved = LS.getView()`):
   - Parse `var urlTab = (location.pathname.split('/')[2] || '').toLowerCase()`.
   - If `urlTab` is a valid slug (`VIEWS` includes it, or it equals
     `past-slides`), it **overrides** the `localStorage` last-tab.
   - The existing availability fallbacks still apply (e.g. `summary`/`notes`/
     `agenda` not yet available → `slides`); the URL self-corrects because
     `showView('slides')` then rewrites it.
   - `past-slides` ⇒ `showView('slides')` + `openPastSlides()` + `_setTabUrl('past-slides')`.
   - empty / unknown ⇒ today's default behavior unchanged.

4. **Consequence:** opening the bare `/<session>/` rewrites to
   `/<session>/slides` once the default tab resolves — consistent with "the URL
   always reflects the active tab."

5. **Audit:** confirm no other code reads `pathname` expecting exactly two
   segments. Known reads — `_sessionId` capture (`split('/')[1]`), the WS-close
   redirect to `/` (absolute), and `notes.html` (`split('/')[1]`) — all remain
   correct with a trailing slug.

## Verification

- **Backend (FastAPI TestClient):** `/<s>/notes` and `/<s>/files` serve the SPA
  (200, participant marker present); `/<s>/notes-print` serves the read-only
  page; `/<s>/garbage` → 404; `/<s>/` unchanged.
- **Hermetic E2E (Docker Playwright):** deep-link `/<s>/notes` lands on the Notes
  tab; clicking Files updates the address bar to `/<s>/files`; screenshot the
  address bar as proof.
- Regenerate `openapi.json` / `API.md` if the OpenAPI contract snapshot picks up
  the route change; run `bash tests/check-all.sh`.
- Confirm the change live in production after deploy.

## Risks / notes

- No internal links to the old standalone `/notes` page were found; a grep for
  references is part of implementation, updating any that exist to `/notes-print`.
- Talk sessions: participant slugs serve `talk.html`, which ignores the slug
  (acceptable; talk deep-linking is a separate future task).
