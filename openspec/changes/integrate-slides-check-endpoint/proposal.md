## Why

Participant slide loading currently skips the daemon `check` endpoint and goes directly to Railway PDF download. This breaks the intended flow where Railway should serve the PDF only after daemon-triggered availability checks, causing avoidable slide load failures during live sessions.

## What Changes

- Update participant slide-loading flow to call the daemon-backed `check` endpoint before requesting the PDF binary.
- Ensure the `check` call supports both outcomes: immediate success when PDF already exists, or async preparation trigger when it must be downloaded/prepared first.
- Make participant JavaScript wait for successful `check` completion before attempting the Railway PDF download URL.
- Define participant-visible behavior for temporary unavailability (retry/wait states) to avoid premature PDF fetch attempts.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `slides`: Change participant slide retrieval contract so readiness must be confirmed through `check` before downloading the PDF from Railway.

## Impact

- Frontend: `static/participant.js` slide fetch sequence and error/retry handling.
- Backend/daemon integration: existing slides readiness/check endpoint contract becomes a required precondition for participant download.
- Specs: delta spec updates under `specs/slides/` to codify mandatory check-then-download flow.
