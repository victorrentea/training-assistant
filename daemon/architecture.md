# Training Daemon Architecture

This document describes the current runtime data flow and responsibilities of `training_daemon.py` and related daemon modules.

## Overview

`training_daemon.py` runs on the trainer's Mac and acts as the local orchestration process between:

- local transcript files (`TRANSCRIPTION_FOLDER`)
- local session artifacts (`SESSIONS_FOLDER`)
- the backend server (`WORKSHOP_SERVER_URL`)
- Claude API calls (quiz/summarizer/debate cleanup)

It is a polling-based daemon with multiple periodic loops in one process.

## Core Transcript Data Flow

```mermaid
flowchart LR
  A[Raw transcript files<br/>YYYYMMDD HHMM Transcription.txt] -->|incremental read + offset| B[transcript_normalizer]
  B --> C[normalization.offset.txt<br/>state per raw file]
  B --> D[Normalized files<br/>YYYY-MM-DD transcription.txt]

  D --> E[quiz_core.load_transcription_files]
  E --> F[Quiz generation window<br/>last N minutes]
  E --> G[Summarizer input<br/>full/incremental]
  E --> H[Transcript status push<br/>line_count/latest_ts]

  D --> I[transcript_query/load_normalized_entries]
  I --> J[/api/session/interval-lines.txt]
  I --> K[startup transcript log]
```

## Polling/Periodic Loops

## Main daemon loop (`DAEMON_POLL_INTERVAL`)

Runs continuously and handles:

1. host requests polling:
- `/api/quiz-request`
- `/api/quiz-refine`
- `/api/debate/ai-request`
- `/api/session/request`

2. session sync / restore / persistence:
- sync session/talk state to backend
- persist daemon session state to disk
- restore from `session_state.json` when needed

3. transcript operations:
- `TranscriptNormalizerRunner.tick()`
- transcript stats push every ~10s to `/api/transcript-status`

4. token usage push every ~10s to `/api/token-usage`

5. summary force polling and summarizer execution

## Transcript normalizer loop

Implemented by `daemon/transcript_normalizer.py`, called by `TranscriptNormalizerRunner`:

- reads only appended bytes from raw transcript files
- keeps state in `normalization.offset.txt` (single shared file, per-raw-file map)
- writes normalized lines to daily files:
  - `YYYY-MM-DD transcription.txt`
- logs:
  - `Normalized X lines` (common case 1 source -> 1 output)
  - or full multi-file message when applicable

## Responsibilities of the Daemon

1. Quiz orchestration
- receives quiz requests from backend
- builds transcript/topic prompt input
- calls Claude
- posts quiz preview/status back to backend

2. Quiz refinement
- refines question or option based on host action

3. Debate AI cleanup
- receives debate cleanup request
- runs LLM cleanup/merge/new-arguments
- posts AI result to backend

4. Live summary generation
- reads transcript (now from normalized files)
- reads notes
- creates incremental/full key points
- posts summary points

5. Transcript normalization pipeline
- raw -> normalized conversion with offset tracking
- provides normalized source-of-truth for downstream consumers

6. Transcript status/telemetry
- computes and pushes:
  - `line_count`
  - `total_lines`
  - `latest_ts`
- pushes LLM token usage/cost counters

7. Session lifecycle automation
- start/end/pause/resume/talk actions via polled session commands
- autosave/restore state to session files
- daily timing hooks (warning/pause/end/start logic)

8. Local indexer bootstrapping
- starts materials indexer for RAG search (slides/books)

## Source of Truth: Transcript Inputs

Outside the normalizer, transcript consumers now read **normalized** files:

- `quiz_core.load_transcription_files()` -> normalized only (`YYYY-MM-DD transcription.txt`)
- summarizer uses `load_transcription_files()`
- transcript status in `training_daemon.py` uses `load_transcription_files()`
- startup session transcript log uses `load_normalized_entries()`
- `/api/session/interval-lines.txt` uses `load_normalized_entries()`

Raw transcript files are now operationally needed only for normalization (and optional timestamp heartbeat append).

## Key Files

- `training_daemon.py` — process orchestration and polling loops
- `daemon/transcript_normalizer.py` — incremental raw -> normalized conversion
- `daemon/transcript_query.py` — normalized transcript range reader (manual/utility + shared loader)
- `quiz_core.py` — transcript loading and extraction for quiz/summarizer/status
- `daemon/summarizer.py` — summary generation pipeline
- `routers/session.py` — interval export endpoint from normalized transcripts

## Configuration

Important env vars:

- `TRANSCRIPTION_FOLDER`
- `SESSIONS_FOLDER`
- `WORKSHOP_SERVER_URL`
- `HOST_USERNAME`, `HOST_PASSWORD`
- `ANTHROPIC_API_KEY`
- `TRANSCRIPT_NORMALIZER_ENABLED`
- `TRANSCRIPT_NORMALIZER_INTERVAL_SECONDS`
- `TRANSCRIPT_TIMESTAMP_INTERVAL_SECONDS`

## Notes

- Normalized transcript files are minute-granularity (`[HH:MM]`), not second-granularity.
- Cross-day queries are supported by loading multiple `YYYY-MM-DD transcription.txt` files.
- If no normalized files exist, transcript-dependent flows now fail fast with explicit logs/errors.

## Persisted Session State

- Global daemon state + per-session snapshot schema/class diagram: `docs/daemon-persisted-state.md`
