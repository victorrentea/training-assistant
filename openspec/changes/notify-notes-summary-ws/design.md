## Context

The daemon currently serves notes and summary through REST endpoints, while real-time channels do not announce content freshness for these files. The existing flow requires host/participants to poll manually to discover updates. Session files are local on the trainer machine, with `ai-summary.md` for key points and one `*.txt` notes file in the session folder.

## Goals / Non-Goals

**Goals:**
- Detect updates to `ai-summary.md` and the session notes `*.txt` file with low latency.
- Broadcast one WS event to both participants and host whenever either file changes.
- Include non-empty line count in the event payload so UIs can show immediate freshness/quantity hints.
- Keep current REST endpoints unchanged for full-content retrieval.

**Non-Goals:**
- Sending full notes/summary file content over WS.
- Supporting multiple notes text files in one session folder.
- Introducing new persistence or database storage.

## Decisions

1. Reuse the daemon orchestrator loop for file change detection.
Rationale: the loop already tracks session-folder bound resources (slides/status), so adding notes/summary mtimes keeps architecture simple.
Alternative considered: dedicated filesystem watcher thread (`watchdog`). Rejected for now to avoid dependency/daemon lifecycle complexity for two files.

2. Use a single shared WS message type for both documents.
Rationale: one event shape simplifies host/participant handlers and contract tests.
Proposed payload fields: `document` (`"notes"|"summary"`), `non_empty_lines` (int), `updated_at` (ISO timestamp).
Alternative considered: separate message types (`notes_updated`, `summary_updated`). Rejected due to duplicate handling logic.

3. Publish to both channels from the daemon WS message registry.
Rationale: requirement explicitly needs host and participant notifications; current typed-message pipeline already supports broadcast + host push patterns.
Alternative considered: participant-only + host polling. Rejected because host also needs immediate awareness.

4. Keep WS as notification-only and fetch content through existing REST endpoints.
Rationale: preserves existing API contract and avoids heavy payloads on WS.
Alternative considered: include markdown/text in WS payload. Rejected as unnecessary bandwidth + coupling.

## Risks / Trade-offs

- [Polling misses very rapid transient edits between ticks] -> Mitigation: track file mtime + last known line count and emit on every detected state transition; polling interval remains short.
- [Editor writes may trigger multiple near-identical change events] -> Mitigation: deduplicate by `(document, mtime, non_empty_lines)` snapshot before broadcasting.
- [Notes file ambiguity if multiple `*.txt` exist] -> Mitigation: keep current assumption of single notes file; select latest modified `*.txt` consistently.
- [UI may display stale full content after notification] -> Mitigation: clients treat WS as invalidate signal and immediately re-fetch via existing endpoints.
