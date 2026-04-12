# Design: Document Daemon ↔ Railway Internal APIs

## Problem

The daemon↔railway internal communication (WS control messages + REST calls) is undocumented. Only participant-facing and host-facing APIs appear in API.md. Internal messages like `participant_presence`, `sync_files`, `proxy_request`, etc. have no spec files, no contract tests, and no generated documentation.

## Scope

Document only the internal daemon↔railway protocol — NOT the proxied participant/host endpoints (already covered).

### Messages & Endpoints to Document

**Railway → Daemon WS:**
- `participant_presence` (feature: `identity`)
- `daemon_state_push` (feature: `identity`)
- `sync_files` (feature: `slides`)
- `download_pdf` (feature: `slides`)
- `pdf_download_complete` (feature: `slides`)
- `file_ready_for_download` (feature: `paste_upload`)
- `summary_force` (feature: `notes_summary`)
- `summary_full_reset` (feature: `notes_summary`)
- `scores_reset` (feature: `scores_leaderboard`)
- `proxy_request` (feature: `infrastructure`)

**Daemon → Railway WS:**
- `set_session_id` (feature: `session_management`)
- `code_timestamp` (feature: `infrastructure`)
- `broadcast` (feature: `infrastructure`)
- `send_to_host` (feature: `infrastructure`)
- `proxy_response` (feature: `infrastructure`)
- `daemon_ping` (feature: `infrastructure`)

**Daemon → Railway REST:**
- `GET /api/session/active` (feature: `session_management`)
- `GET /upload/{file_id}` (feature: `paste_upload`)
- `POST /upload/{file_id}/ack` (feature: `paste_upload`)

**Railway REST (daemon-facing):**
- `POST /api/slides/download-from-gdrive/{slug}` (feature: `slides`)

## New Files

### `docs/railway-openapi.yaml`
OpenAPI 3.1.0 spec for the ~4 daemon↔railway REST endpoints. Same conventions as `docs/openapi.yaml`: `x-feature` on every operation, Pydantic-aligned schemas in `components/schemas`.

### `docs/railway-ws.yaml`
AsyncAPI 2.6.0 spec for all daemon↔railway WS messages. Two channels:
- `subscribe` (railway → daemon): messages the daemon receives
- `publish` (daemon → railway): messages the daemon sends

Same conventions as `participant-ws.yaml` / `host-ws.yaml`: `x-feature` on every message, payload schemas with `type` discriminator field.

## API.md Integration

New subsection types **"Daemon REST"** and **"Daemon WS"** rendered alongside existing "Host REST", "Host WS", "Participant REST", "Participant WS" within each feature section.

Messages are assigned to existing feature sections where they have business semantics (e.g. `participant_presence` → Identity, `sync_files` → Slides). A new **"Infrastructure"** feature section covers transport plumbing: `proxy_request`, `proxy_response`, `daemon_ping`, `set_session_id`, `code_timestamp`, `broadcast`, `send_to_host`.

### Generator Script Changes
- `scripts/generate_apis_md.py` accepts new args: `--railway-openapi` and `--railway-ws`
- Loads the two new spec files
- Renders "Daemon REST" / "Daemon WS" subsections per feature
- New `infrastructure` entry in `FEATURE_LABELS` and `FEATURE_ORDER`

## Contract Tests

### `tests/daemon/test_railway_api_contract.py`
Validates `railway-openapi.yaml` against actual Railway FastAPI routes:
- Path existence
- Method matching
- Request/response schema alignment
- `x-feature` presence on all operations

### `tests/daemon/test_railway_ws_contract.py`
Validates `railway-ws.yaml` against:
- Daemon WS handler registrations in `daemon/__main__.py`
- `push_to_daemon()` call sites in railway code
- `x-feature` presence on all messages
- Payload field matching against message dicts in source code

## Feature ID Additions

Add `infrastructure` to:
- `FEATURE_LABELS` in generator script
- `FEATURE_ORDER` in generator script
- `docs/api-reference-features.md`

## Out of Scope

- Proxied participant/host REST endpoints (already documented)
- `broadcast`/`send_to_host` inner event payloads (already documented as participant/host WS messages)
- Refactoring existing specs or tests
