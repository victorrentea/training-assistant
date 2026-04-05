## Context

The participant header bar has two buttons — Notes (📝) and Key Points (🧠) — that are enabled or disabled based on whether content exists. Previously the `/state` REST endpoint returned the full notes text and all summary points on every load, coupling payload size to content size. The daemon already polls notes/summary files on disk every loop iteration; we leveraged that probe to drive WS broadcasts.

## Goals / Non-Goals

**Goals:**
- `/state` returns only counts (`notes_count`, `summary_count`), not full content
- Daemon broadcasts `notes_updated {count}` and `summary_updated {count}` on file change and on WS reconnect
- Participant and host bars enable/disable and display counts from these counts
- Count label in the bar flashes yellow when a WS update arrives (not on page load)
- Full content is fetched on demand when the user opens the overlay
- Hermetic test covers: state-driven enable, WS-driven update, yellow flash

**Non-Goals:**
- No Railway-side state for these counts (Railway stays stateless except PDF)
- No periodic broadcast (only on change and on reconnect)
- No changes to the host REST endpoints for notes/summary content

## Decisions

**Count semantics — non-empty lines vs. point objects**
- `notes_count`: number of non-empty lines in the `.txt` file (consistent with daemon probe)
- `summary_count`: number of parsed point objects from `ai-summary.md` (what the UI actually renders)
- Rationale: each count reflects what the badge label number means to the user

**Flash triggered by WS, not by state load**
- Rationale: on page load the count is expected (no surprise); a WS update mid-session signals live activity worth drawing attention to. `updateNotesCount`/`updateSummaryCount` accept a `flash` boolean defaulting to `false`; WS handlers pass `true`.

**No Railway caching of counts**
- Participants who connect between daemon broadcasts miss the count until the next file change or daemon reconnect (which re-broadcasts). Acceptable: notes/summary change infrequently and the daemon reconnects on every Railway restart.

## Risks / Trade-offs

- [New participant connects before first daemon broadcast] → count stays 0, buttons disabled until next change or reconnect. Mitigation: daemon broadcasts on WS reconnect, which happens shortly after Railway starts.
- [Stale count in header if daemon disconnects mid-session] → count is not decremented, but content may differ. Acceptable: counts are informational; the overlay fetch is authoritative.
