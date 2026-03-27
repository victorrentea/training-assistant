# Summary

## Purpose
Manages session key points, notes content, transcript progress tracking, and LLM token usage. Summary generation is on-demand only (triggered by host or participant); no periodic timer.

## Endpoints
- `POST /api/summary` — daemon posts updated summary points (list of `{text, source, time}`)
- `GET /api/summary` — public; returns current summary points + last updated time
- `POST /api/notes` — daemon posts updated notes content
- `GET /api/notes` — public; returns notes content + summary points
- `POST /api/transcript-status` — daemon posts transcript progress (`line_count`, `total_lines`, `latest_ts`)
- `POST /api/summary/force` — public (30s cooldown); participant Key Points button triggers this
- `GET /api/summary/force` — daemon polls for pending force request (clears on read)
- `POST /api/summary/full-reset` — host requests full summary reset (daemon re-processes from scratch)
- `GET /api/summary/full-reset` — daemon polls for pending full-reset request
- `POST /api/token-usage` — daemon posts token usage stats `{input_tokens, output_tokens, estimated_cost_usd}`

## State Fields
Fields in `AppState` owned by this feature:
- `summary_points: list[dict]` — `[{text, source: "notes"|"discussion", time: "HH:MM"}]`
- `summary_updated_at: datetime | None`
- `summary_force_requested: bool` — set by POST /api/summary/force; cleared by daemon on GET
- `summary_reset_requested: bool` — set by POST /api/summary/full-reset
- `notes_content: str | None` — raw session notes markdown
- `transcript_line_count: int` — lines processed so far
- `transcript_total_lines: int` — total lines in current transcript file
- `transcript_latest_ts: str | None` — latest timestamp seen
- `transcript_last_content_at: datetime | None` — last time line_count increased
- `token_usage: dict` — `{input_tokens, output_tokens, estimated_cost_usd}`

## Design Decisions
- Summary generation is on-demand only: triggered by host (brain badge) or participant (Key Points button via `POST /api/summary/force`).
- `POST /api/summary/force` is public (no auth) but has a 30s in-process cooldown to prevent spam.
- The daemon uses delta-based summarization: it only processes new transcript lines since the last summary.
- Two-tier summary: `"notes"` points come from host-written notes; `"discussion"` points come from transcript.
