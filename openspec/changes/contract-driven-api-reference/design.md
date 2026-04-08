## Context

The codebase already has contract tests that validate OpenAPI and AsyncAPI against implementation, but `API.md` is still maintained manually and does not have the same sync guarantees. The result is drift in endpoints, WS messages, and behavioral notes. The user requires feature-based structure and automatic export of documentation details directly from contracts/code.

## Goals / Non-Goals

**Goals:**
- Generate `API.md` exclusively from daemon contracts (`docs/openapi.yaml`, `docs/participant-ws.yaml`, `docs/host-ws.yaml`).
- Make feature classification explicit, verifiable, and free of fragile heuristics.
- Encode important notes in contracts (`x-doc-notes`, `summary`, `description`) and export them automatically.
- Make CI/tests block any drift between contracts and `API.md`.

**Non-Goals:**
- Defining/exporting `global/session state` structure in JSON Schema (next phase).
- Keeping manual narrative sections inside `API.md`.
- Aggregating Railway app `openapi.json` into the same document.

## Decisions

1. `API.md` is the official generated output.
- Rationale: the main API document becomes correct-by-construction.
- Alternative: keep a separate generated file (`API.generated.md`) in parallel; rejected because it allows drift in the main document.

2. Feature classification is mandatory in contracts.
- REST: `x-feature` required on every OpenAPI operation.
- WS: `x-feature` required on every AsyncAPI message.
- Rationale: eliminates ad-hoc mappings and implicit interpretation.
- Alternative: derive from `tags`; rejected because it is inconsistent for mixed cases.

3. Contractual notes are standardized.
- `x-doc-notes` (list of strings) + `summary` + `description` are the only note sources for output.
- Rationale: important knowledge is versioned in contracts, not in external manual prose.

4. Generator is deterministic with stable rendering rules.
- Fixed structure: `Feature -> Participant REST/WS -> Host REST/WS`.
- Schema field rendering (enum/object/map/nullability) is derived exclusively from contract schema.
- Rationale: predictable output, easy to test, diff-friendly.

5. Automated completeness and freshness checks.
- OpenAPI coverage: every operation appears in output.
- AsyncAPI coverage: every message appears in output.
- Metadata coverage: every operation/message has `x-feature`.
- Freshness: committed `API.md` equals current generator output.
- Rationale: continuous enforcement without manual review.

## Risks / Trade-offs

- [Initial metadata rollout] Higher initial effort to add `x-feature`/`x-doc-notes` everywhere.
  - Mitigation: incremental rollout by module + precise failing-test diagnostics.

- [Decorator noise] `openapi_extra` adds metadata alongside endpoint logic.
  - Mitigation: shared helper/constant and consistent metadata convention.

- [Narrative context removed from same file] `API.md` no longer carries free-form architecture flows.
  - Mitigation: keep a separate narrative architecture/flow document when needed.

- [Note quality depends on discipline] `x-doc-notes` quality can degrade over time.
  - Mitigation: lightweight guideline + review checklist for meaningful notes.

## Migration Plan

1. Define metadata schema (`x-feature`, `x-doc-notes`) and usage rules.
2. Add `x-feature` to all REST operations and WS messages in scope.
3. Add `x-doc-notes` for important behaviors (timeouts, limits, invariants, side effects).
4. Generate full `API.md` from contracts and remove manual sections from that file.
5. Enable coverage/freshness tests in the standard suite.
6. Rollback plan: revert to previous `API.md` commit and temporarily disable freshness check.

## Open Questions

- None blocking for this change.
