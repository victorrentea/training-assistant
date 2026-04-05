## Why

Participants currently hit a broken path in production where `GET /{sid}/api/slides/check/{slug}` returns `200`, but the immediate PDF fetch at `GET /{sid}/api/slides/download/{slug}` returns `404`. This breaks the user promise that a successful check means the PDF is downloadable.

## What Changes

- Tighten the `/check` contract so a `200` response means the slug is actually downloadable from Railway at that moment.
- Stop relying on daemon-local "cached" state as sufficient proof of Railway availability.
- Update participant slide download interactions to use the same readiness gate as in-view loading.
- Add regression coverage for the `check=200` then `download=404` mismatch.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `slides`: Strengthen cache-readiness semantics and participant download flow so successful readiness checks are aligned with actual Railway download availability.

## Impact

- Daemon slides readiness endpoint logic in `daemon/slides/router.py`.
- Participant download click path in `static/participant.js`.
- Potentially Railway slides download probing/supporting helpers in `railway/features/slides/router.py`.
- Tests around slides check/download behavior (daemon + participant integration).
