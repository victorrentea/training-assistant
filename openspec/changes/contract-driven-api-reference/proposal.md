## Why

`API.md` is maintained manually and has drifted from the real contracts (OpenAPI/AsyncAPI), even though the contracts are already validated by tests. We need the API documentation used day-to-day to be generated automatically from the same source of truth.

## What Changes

- Introduce a contract-driven generator that produces `API.md` exclusively from `docs/openapi.yaml`, `docs/participant-ws.yaml`, and `docs/host-ws.yaml`.
- Make feature classification explicit and exportable from contracts:
  - REST: `x-feature` on every OpenAPI operation (via FastAPI `openapi_extra`).
  - WS: `x-feature` on every AsyncAPI message.
- Make important notes automatically exportable from contracts:
  - `x-doc-notes` + `summary` + `description`.
- **BREAKING (workflow):** `API.md` becomes a generated file; manual narrative content no longer lives in this file.
- Add automated checks for full coverage (all endpoints and all WS messages appear in output) and synchronization (`API.md` regenerates identically).

## Capabilities

### New Capabilities
- `api-reference-generation`: generates feature-grouped API reference directly from contracts, including request/response/payload shapes and contractual notes.

### Modified Capabilities
- `session`: endpoint documentation becomes contract-driven in `API.md`.
- `slides`: endpoint and WS message documentation becomes contract-driven in `API.md`.

## Impact

- `scripts/generate_apis_md.py` becomes the official pipeline for `API.md`.
- FastAPI routers gain OpenAPI metadata (`x-feature`, `x-doc-notes`) at operation level.
- AsyncAPI files (`docs/participant-ws.yaml`, `docs/host-ws.yaml`) gain `x-feature` and optional `x-doc-notes` per message.
- Documentation/contract tests are extended to validate coverage and synchronization.
