## Why

Slides cache indicators are currently inaccurate: participants can see green/cached before Railway actually has the PDF, and loading indicators sometimes never transition to cached after download completion. This misleads users and degrades trust in the slides experience during live sessions.

## What Changes

- Align initial cache status computation with Railway-hosted cached PDFs, not local daemon publish artifacts.
- Ensure `/api/slides` and WS cache updates expose status values that reflect Railway download availability.
- Make daemon process `pdf_download_complete` into durable cache state updates and broadcast those updates so participant and host UI transition from loading to cached reliably.
- Add regression coverage for startup status accuracy and post-download status transitions.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `slides`: Cache status semantics and propagation must reflect actual Railway PDF availability at startup and after download completion.

## Impact

- Affected daemon slides state initialization and `/api/slides` payload population (`daemon/slides/*`).
- Affected Railway↔daemon cache-complete message handling path (`railway/features/ws`, daemon WS handlers).
- Affected participant/host cache status rendering behavior driven by WS updates.
- Affected tests and docs for slides cache status lifecycle.
