# GDrive URL Required for Every Session — Design

**Date:** 2026-05-22
**Status:** Approved for implementation
**Scope:** Backend session lifecycle, participant UI sidebar, removal of obsolete nested-talk concept

## Motivation

Today, `gdrive_url` is held only in `MiscState` (runtime-only, never persisted), and is resolved exactly once at daemon startup from local DriveFS SQLite. If Google Drive isn't running at boot, or DriveFS hasn't synced the folder yet, the URL stays `None` for the daemon's lifetime — there is no on-demand re-resolution. Result: the currently-active session has no GDrive link in the participant view, even though a folder demonstrably exists in Drive.

Every started session must have a GDrive share URL — there is no reason for a session to exist without one. The only legitimate failure case is "Google Drive isn't running"; in that case session creation should be refused outright.

## Goals

1. Sessions cannot exist without a `gdrive_url` — enforced at session creation.
2. URL survives daemon restarts (persisted to `session-state.json`).
3. Participants always receive the URL via initial page load.
4. Host sees an actionable error (`Please start Google Drive`) if GDrive is offline at session-create.
5. Participant sidebar splits "Resources" into two distinct top-level entries: a direct **Google Drive** link and a collapsible **Code** group.
6. Cleanup: the obsolete nested-talk / two-level session concept is removed entirely (no longer used).

## Non-goals

- Auto-creating a folder in Google Drive (we only resolve existing folders).
- On-demand re-resolution after session creation (URL is captured once at create time and persisted).
- Migration of historical session-state files (only the active session is touched).

## A. Backend: GDrive URL as a session precondition

### Data model

Add to `PersistedSessionState` (`daemon/persisted_models.py`):

```python
gdrive_url: str | None = None
```

Default `None` so older session files load. New sessions always set it.

`MiscState.gdrive_url` (`daemon/misc/state.py`) becomes a read-through view of the active session's persisted field — single source of truth is the session-state file.

### `POST /api/session/create` flow

Sequence (in `daemon/session/router.py` / the orchestrator):

1. Resolve / create session folder (as today).
2. Call `resolve_gdrive_url(folder)` synchronously.
3. If `None` → return `503` with body `{"error": "gdrive_unavailable", "message": "Please start Google Drive"}`. Session is **not** persisted; folder created on disk is left as-is (cheap, no rollback required).
4. If URL is returned → write into the new `PersistedSessionState`, then continue normal start flow.

### Host UI

`static/host.js`: when session-create returns 503 with `error: "gdrive_unavailable"`, call `toast('Please start Google Drive')` and abort — the "Start" button stays as "Start" (no spinner stuck).

### Daemon boot auto-resolve

In `daemon/__main__.py` startup path: after loading the active session, if `session.gdrive_url is None`, attempt one resolution. If successful, persist into the session state file (in place) and log at INFO. If unsuccessful, log a WARN and leave `None` — the running session keeps running, but the next "Start Session" click will be blocked until GDrive is available.

### Participant delivery

No new endpoint. `GET /api/{session_id}/participant/state` already returns `gdrive_url` from `MiscState`. We only rewire the source.

## B. Participant UI: Resources → Google Drive + Code

File: `static/participant.html` (sidebar block ~lines 345-421).

**Before:**

```
Resources [cloud icon] ▼ (collapsible)
  ├─ Google Drive [folder_shared]
  └─ Git repos…
```

**After:**

```
Google Drive [folder_shared]                      [open_in_new]
Code [git_commit, sized up] ▼ (collapsible)
  └─ Git repo entries…
```

Rules:

- "Google Drive" is a single top-level `<a>` with `target="_blank" rel="noopener"`, href = `state.gdrive_url`. Right-aligned trailing `open_in_new` material symbol.
- Hide the entry if `gdrive_url` is absent (defensive — backend now guarantees presence).
- "Code" header reuses the existing Resources collapsible interaction. The git-commit material symbol is sized one step larger than other nav icons (e.g. `font-size: 22px` if siblings are `18px`).
- Remove the existing "Resources" wrapper entirely.

## C. Nested-talk concept removal

The two-level session hierarchy (main session containing a nested "talk", typically used for lunch-break demos) has been abandoned. Remove every trace:

- Fields on session models / state (e.g. `talk_*`, `parent_session_id`, talk-presentation state).
- Session-request actions for creating / ending a talk.
- Host UI buttons / endpoints for the talk lifecycle.
- Tests that exercise nested talks.
- CLAUDE.md line: "Max 2 levels (main + talk)" → simplify to a single session concept.
- Memory file `project_session_management.md` (mentions nested lunch-break talks).

Net behaviour: one flat session at a time. Stopping/starting begets a new session, no nesting.

## Error handling

- 503 on session-create when GDrive offline. Host UI shows toast.
- Boot-time resolution failure: WARN log only, session continues, fresh "Start" blocked until GDrive returns.
- Network/SQLite errors inside `resolve_gdrive_url`: treat as `None` (already today's behaviour).

## Testing

- Unit: `PersistedSessionState` round-trips with `gdrive_url`.
- Unit: session-create returns 503 when `resolve_gdrive_url` returns `None`; happy path stores URL.
- Hermetic / E2E: participant `GET /api/{session}/participant/state` includes `gdrive_url` after a clean start. Mock or stub `resolve_gdrive_url` in tests.
- Manual: confirm participant sidebar shows two new entries; clicking "Google Drive" opens correct URL in new tab.

## Execution plan

Two parallel sub-agents (Sonnet):

1. **Backend + nested-talk cleanup agent** — sections A and C in one context (both touch `PersistedSessionState` and surrounding session model code, easier to coordinate in one agent than across two).
2. **Participant UI agent** — section B (mostly `static/participant.html`, isolated from backend changes).

Each agent commits and pushes to `master` (pull-rebase first per repo convention). Main thread verifies on prod after both land.
