# Ask Name Before Join Design

## Goal
Require participants to choose identity before joining a session, while preserving smooth return for known UUIDs and optional host-machine testing shortcuts.

## Decisions

1. Add `POST /api/participant/rejoin` (daemon participant router)
- Input: `X-Participant-ID` header.
- Behavior: lookup only.
- `200 {name, avatar}` when UUID exists in current session.
- `404` when UUID does not exist in current session.
- No participant creation, no score init, no host broadcast/write-back events.

2. Extend `POST /api/participant/register`
- Accept optional body field `name`.
- If UUID already registered: return existing `{name, avatar}` unchanged.
- If new UUID and `name` provided:
  - trim and validate non-empty max 32 chars,
  - reject duplicates with `409`,
  - assign random available avatar across all known session participants (online and offline).
- If new UUID and `name` omitted/empty:
  - assign random available participant name,
  - assign random available avatar for the new participant (same global availability rules).

3. Participant pre-join UX
- Do not connect websocket until identity is resolved.
- If UUID exists:
  - call `/api/participant/rejoin`.
  - on `200`, continue to main screen and websocket connect.
  - on `404`, show pre-join UI, except optional local host-machine fallback path.
- If UUID missing: show pre-join UI.
- Pre-join actions:
  - manual: call `/api/participant/register` with `{name}`.
  - random: call `/api/participant/register` with `{}`.

4. Host-machine testing path
- Landing page gets a small left-bottom checkbox that controls cookie `ON_HOST_MACHINE=true`.
- Localhost daemon active-session probing is performed only when this cookie is set.
- Local fallback naming is testing-only:
  - use `<local name> (local)` as candidate,
  - if Railway `/register` returns `409`, append `+` and retry until accepted.

5. Post-join onboarding update
- Remove post-join checklist logic that tracks whether participant renamed from assigned name.

## Risks and mitigations

- Existing e2e assumes immediate auto-join.
  - Mitigation: default most automated flows to click random pre-join path for simplicity.
- Localhost probing can fail due environment/CORS/network.
  - Mitigation: guard behind explicit cookie and treat path as best-effort fallback only.
