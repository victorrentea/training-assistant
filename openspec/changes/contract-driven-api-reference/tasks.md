## 1. Metadata Contract Foundation

- [x] 1.1 Define and document canonical feature IDs used by generated API reference.
- [x] 1.2 Add `x-feature` to every daemon REST operation in exported OpenAPI.
- [x] 1.3 Add `x-feature` to every participant and host AsyncAPI message.
- [x] 1.4 Add `x-doc-notes` where operational behavior is important (timeouts, limits, invariants, side effects).

## 2. Generator and Rendering

- [x] 2.1 Finalize generator inputs to daemon contracts only: `docs/openapi.yaml`, `docs/participant-ws.yaml`, `docs/host-ws.yaml`.
- [x] 2.2 Render sections by feature with fixed structure: Participant REST/WS, Host REST/WS.
- [x] 2.3 Render schema shapes for request/response/payload including enum/map/nullability hints.
- [x] 2.4 Render notes from `x-doc-notes`, `summary`, and `description` without manual additions.

## 3. Verification and Drift Protection

- [x] 3.1 Add coverage test: all OpenAPI operations appear in generated output.
- [x] 3.2 Add coverage test: all AsyncAPI messages appear in generated output.
- [x] 3.3 Add metadata test: all REST operations include `x-feature`.
- [x] 3.4 Add metadata test: all WS messages include `x-feature`.
- [x] 3.5 Add freshness test: committed `API.md` must match current generator output.

## 4. Migration to Generated API.md

- [x] 4.1 Replace manual `API.md` content with generated output.
- [x] 4.2 Remove non-contract narrative sections from `API.md`.
- [x] 4.3 Document regeneration command and contributor workflow in project docs.
- [x] 4.4 Run full targeted verification and attach proof in change review.


## Review

- Proof: `python3 -m tests.daemon.test_api_contract --regenerate`
- Proof: `python3 scripts/generate_apis_md.py --output API.md`
- Proof: `pytest -q tests/daemon/test_api_contract.py tests/daemon/test_ws_contract.py tests/docs/test_generate_apis_md.py`
- Result: `20 passed`
