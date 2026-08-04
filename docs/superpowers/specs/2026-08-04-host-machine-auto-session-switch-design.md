# Host-machine auto session switch

**Date:** 2026-08-04
**Status:** Approved design, pending implementation plan

## Problem

When Victor opens Interact as host, jumping from an old session to the newly
started one is manual and error-prone: a tab left on `/{old_id}/` stays there
forever, because only `landing.html` polls the local daemon for the active
session. The result is a trainer looking at a dead session while the audience
is in a live one.

Two things must happen automatically, but *only* on the trainer's own machine:

1. The page navigates to the new session as soon as the daemon reports one.
2. The trainer joins that session identified as `Victor (trainer)`.

## Threat model

The premise, confirmed against the code:

> **A session join code is a secret shared with that session's participants.**
> Nobody outside a session may learn its code.

This is already the repo's stated position. `railway/shared/rate_limit.py:3-11`
describes `/{id}/api/status`, `/api/status` and `/api/is-active-session` as an
enumeration oracle over guessable session ids and throttles them for exactly
this reason. Codes are 6 characters from a 33-symbol alphabet (~30 bits),
generated with `secrets.choice`, so they resist prediction but not unlimited
probing — hence the rate limit.

The security boundary for this feature is therefore **"can this browser reach
the trainer's `127.0.0.1:1234`?"**, and nothing else. That boundary is already
enforced by three independent mechanisms in `daemon/host_server.py`:

| Attack | Blocked by |
| --- | --- |
| Remote/LAN request to the daemon | `uvicorn` binds `127.0.0.1` (`daemon/host_server.py:359`) |
| Malicious page + DNS rebinding to `127.0.0.1` | `_local_access_guard` rejects any non-loopback `Host` header (`daemon/host_server.py:158`) |
| Cross-origin fetch from another site | CORS `allow_origins=["https://interact.victorrentea.ro"]` (`daemon/host_server.py:151`) |
| Anyone reaching the endpoint through the public backend | Railway forwards only `/api/participant/{path:path}` plus two fixed slides routes (`railway/features/ws/proxy_bridge.py:94`) |

The last row was the load-bearing one for this design, and **it was wrong as
originally stated.** The claim "any endpoint outside `/api/participant/*` is
unreachable from the internet" survived until adversarial testing, which broke
it:

```
POST /{session}/api/participant/../host-machine/claim-trainer
```

Railway matches the **raw** request path, so its catch-all captured the
traversal and forwarded it verbatim. The daemon built the target URL by string
concatenation, and `httpx` then **resolved** the dot-segments, landing the call
on the unauthenticated claim endpoint — with the `Host` header stripped by
Railway, so the anti-rebinding guard saw loopback and allowed it.

The lesson generalizes beyond this feature: **a route prefix is not a security
boundary when something downstream re-parses the path.** Reachability must be
enforced at the hop that builds the request, not inferred from what the router
upstream is *expected* to match. `daemon/proxy_handler.py::is_safe_proxy_path`
is where it is now enforced, and every proxied request is stamped
`X-Railway-Proxied` so privileged endpoints can refuse anything that arrived
from the internet.

With those in place the original property holds: a participant on their own
machine who calls `127.0.0.1:1234` reaches their own computer, learns nothing
about the trainer's session, and at most fools themselves.

Because of this, **no secret needs to travel through Railway.** An earlier
draft proposed a daemon-issued single-use nonce carried on the participant
registration call; it is dropped. The privilege is granted locally instead, so
there is no token to intercept, replay, or guess.

Note this decision survived the escalation above: the nonce would not have
helped, because the traversal reached the endpoint that *issues* trust, not a
channel carrying it. What was missing was path validation, not a secret.

## Design

### 1. Redirect (`static/participant.html`)

`participant.html` gains the polling that `landing.html` already performs
(`static/landing.html:479-490`): a 1s poll of
`GET http://localhost:1234/api/session/active`, which already exists
(`daemon/session/router.py:319`) and returns `{session_id}` or null.

If the returned `session_id` differs from the one in the URL, the page
navigates to `/{new_id}/` **instantly**, with no confirmation bar.

Polling runs only while the `ON_HOST_MACHINE` cookie is set. This cookie is
**not a security gate** — it is JS-readable and anyone can set it. It is
demoted, explicitly, to a performance hint that keeps participants' browsers
from firing pointless requests at their own localhost. Failures are swallowed
silently.

### 2. Identity (`POST /api/host-machine/claim-trainer`)

A new daemon-local endpoint, deliberately **not** under `/api/participant/*`:

```
POST http://127.0.0.1:1234/api/host-machine/claim-trainer
body: { "participant_id": "<uuid>" }
→    { "granted": true, "display_name": "Victor (trainer)" }
```

The daemon records the UUID in a per-session set of claimed trainers and sets
the display name. Registration arrives over a different path (browser →
Railway → WS → daemon), so the two can land in either order; the claim set is
therefore consulted both when a claim arrives for an already-registered UUID
and when a registration arrives for an already-claimed UUID. Order-independence
is a requirement, not an optimization.

The trainer badge renders from the server-side flag, never from the name
string. The reserved name lives as a single module constant
(`RESERVED_TRAINER_NAME = "Victor (trainer)"`) used both to name the claimer and
to reject impostors; it is compared after normalizing case and whitespace, and
refused for any participant that has not claimed, so nobody can simply type it
into the name field.

Existing `CORSMiddleware` config already permits this call: `POST` is in
`allow_methods`, `Content-Type` in `allow_headers`, and `allow_private_network`
is enabled for the public-origin → loopback fetch.

### 3. Identity lifetime

On auto-switch the page mints a **new participant UUID** for the new session.
The trainer is a fresh participant there, with a leaderboard that starts clean.

This applies **only to the auto-switch path on the host machine**. Global UUID
storage semantics for ordinary participants are untouched — no migration of
stored identities, no change to the existing `is_host` → `sessionStorage`
behaviour described in `CLAUDE.md`.

## Data flow

```
daemon starts new session
        │
        ▼
GET /api/session/active  ──►  participant.html poll (host machine only)
        │                          │
        │                          ▼  session_id differs
        │                     navigate to /{new_id}/
        │                          │
        │                          ▼  mint new UUID
        │              ┌───────────┴───────────┐
        │              ▼                       ▼
        │   register via Railway     POST /api/host-machine/claim-trainer
        │   (name, UUID)             (UUID, loopback only)
        │              └───────────┬───────────┘
        ▼                          ▼
   daemon reconciles: UUID in claim set → is_trainer = true, name = "Victor (trainer)"
                                   │
                                   ▼
                        broadcast updated participant
```

## Error handling

- Daemon unreachable (not on the host machine, daemon down): poll fails, is
  swallowed, page behaves exactly as today.
- Claim fails while registration succeeded: participant stays an ordinary
  participant under their chosen name. No half-trainer state.
- Redirect loop: the page navigates only when the reported id differs from the
  current URL, so a stable id produces no navigation.
- Session ended while trainer is on it: the daemon reports the new active id
  and the page moves; the read-only "ended" view is not special-cased.

## Testing

Contracts follow the project's Pydantic-first rule; `API.md` is regenerated via
`scripts/generate_apis_md.py`, never edited by hand.

**Regression test that encodes the security invariant:** assert that no daemon
route granting host-machine privilege is reachable under `/api/participant/*`,
so a future refactor cannot silently expose `claim-trainer` through the Railway
catch-all. This is the single test most worth having.

Further coverage:

- Claim before register, and register before claim, both yield a trainer.
- A participant that never claimed is refused the reserved name.
- Non-loopback `Host` header is rejected on the new endpoint.
- Cross-origin request from an origin other than Interact is rejected.

**Adversarial pentest (final step, as requested):** a subagent drives a headless
browser in Docker with no route to the host's port 1234, playing an ordinary
participant, and attempts to (a) reach `claim-trainer` through the public
backend, (b) obtain the trainer's session code by any channel — enumeration,
`/api/status`, the ended-session view, slides links — and (c) claim the reserved
name. The feature ships only if all three fail.

## Non-goals

- Protecting the session code cryptographically. It is a bearer secret typed by
  humans; rate limiting is the existing and adequate mitigation.
- Any confirmation UI for the jump. Instant, by decision.
- Changing UUID storage for ordinary participants.
