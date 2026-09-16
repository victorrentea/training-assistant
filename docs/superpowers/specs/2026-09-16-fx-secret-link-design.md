# Secret FX link — design

**Date:** 2026-09-16
**Status:** approved for planning

## Goal

Let the host hand a secret URL to two or three trusted people in the room.
Opening that URL gives them a page with one big button; pressing it fires a
chosen soundboard tile on the trainer's Mac — exactly as if the trainer had
pressed that tile on the Victor Effects panel himself.

This serves the product goal: the room gets a lever it can pull, and the
spectacle stops being one person's job.

## Vocabulary

- **Tile** — a numbered entry of the 91-tile soundboard (`n`, `asset`,
  `image`, optional `label`, optional paired `effect`). Numbers address tiles,
  never effects.
- **Effect** — a named visual in `EffectsEngine.fireEffect` (`wazzup`,
  `explosion`, …). Some tiles have one, some do not.
- **Press** — the full tile gesture: `stop-all`, play the sound, fire the
  paired visual, and stop that visual when the clip ends.
- **fx link** — the secret URL. One per session, bound to one tile.

## Decisions

| Question | Decision |
|---|---|
| What the link opens | A page with a big trigger button, not a fire-on-load URL |
| How many links | One per session, bound to one tile at a time |
| Default tile | **69** (`69_scream_ghost.mp3`, effect `wazzup`) |
| Abuse control | Server-side cooldown (default 10s) **and** a host master switch |
| Master switch default | **Off** at every session start, like the 🔔 attention switch |
| Token lifetime | Per session, stored in `session-state.json`, with a Rotate button |
| URL shape | `https://interact.victorrentea.ro/fx/<token>` (costs one Railway deploy) |
| Catalog | All 91 tiles, read live from the Effects app |
| Caller identity | Anonymous — the link is the credential |
| Host feedback | Footer badge flashes; tooltip shows when it last fired |

## Architecture

```
Host page ──loopback REST──▶ daemon :1234   /api/{sid}/host/fx/*
                                 │
Trusted person ──▶ interact.victorrentea.ro/fx/<token>
                         │  Railway: path relay + rate limit, no fx state
                         └─ WS /ws/daemon ─▶ daemon /api/participant/fx/<token>
                                                 ├ compare_digest(token)
                                                 ├ enabled? cooldown elapsed?
                                                 └ GET :55123/press/<n>
                                                       └ addons proxy ─▶ :55124
                                                             └ SoundboardPress.press(tile)
```

Railway stays a dumb proxy: it forwards `/fx/*` to the daemon's
`/api/participant/fx/*` and holds no feature state. The daemon owns the token,
the tile selection, the cooldown, the master switch, and the HTML of the
trigger page.

### Why a new route in victor-effects

Pressing a tile is a *sequence*, not a call: `SoundboardPress.press` does
`/effect/stop-all`, then `/sound/play/<asset>?vol=N`, then
`/sound/pressed/<asset>`, then `/sound/stopped/<asset>` after the clip's
duration. The Swift source documents the ordering as a scar from a real bug
where a stop landed after the effect and wiped it. Re-implementing that in
Python would duplicate the scar and drift.

The one existing route that presses *by number*,
`/test/thumbnail-panel/press/<n>`, answers `503 no-panel` unless the panel is
open, so it cannot be used.

Therefore victor-effects gains a panel-independent `GET /press/<n>`, and the
daemon says only "press 69".

## Repository changes

### victor-effects

- `EffectsRouter`: new case `GET /press/<n>` → look `n` up in `TilesManifest`;
  404 `{"ok":false,"reason":"unknown-tile"}` on a miss; otherwise call the
  shared `SoundboardPress.press(tile)` and return its JSON verbatim.
- The press instance must be panel-independent (today it is owned by
  `ThumbnailPanelController`). Hoist it so both the panel and the route share
  one instance — two `SoundboardPress` objects would each keep their own
  `playing`/`generation` and fight over stop-all.
- Test through the existing `SoundboardDispatcher` protocol: assert the route
  emits the four calls in order for a tile with a paired visual, and that an
  unknown `n` dispatches nothing.

### victor-macos-addons

- Add `"/press/"` to `TabletHttpServer.proxiedPrefixes`. One line. Keeps the
  daemon on a single door (`:55123`) and inherits the merged `/ping`, which
  already reports `effectsUp`.

### training-assistant — daemon

**`daemon/effects_client.py`** (new). Thin client for `:55123`, modelled on
`addon_bridge_client`'s best-effort style — short timeouts, never raises,
returns `bool`/`None`:

- `press_tile(n: int) -> bool`
- `fetch_tiles() -> FxCatalog | None` — `GET /tiles`, cached on `effectsHash`
- `fetch_tile_image(path: str) -> bytes | None`
- `is_up() -> bool` — `GET /ping`, reads `effectsUp`

Base URL from `VICTOR_ADDONS_URL`, default `http://127.0.0.1:55123`.

**`daemon/fx/`** (new package, modelled on `daemon/attention/`):

`router.py`, host endpoints under `/api/{session_id}/host/fx`:

| Method | Path | Body / Response |
|---|---|---|
| GET | `/state` | `FxStateResponse(enabled, token, url, tile_n, tile_label, cooldown_seconds, last_fired_at, effects_up)` |
| GET | `/catalog` | `FxCatalogResponse(tiles: list[FxTile])`, `FxTile(n, label, effect, image, has_effect)` |
| POST | `/toggle` | → `FxStateResponse` (master switch) |
| POST | `/tile` | `FxTileRequest(n: int)` → `FxStateResponse` |
| POST | `/cooldown` | `FxCooldownRequest(seconds: int, ge=0, le=300)` → `FxStateResponse` |
| POST | `/rotate` | → `FxStateResponse` with a fresh token |
| POST | `/test` | fires the selected tile from the host page. Bypasses the token and the master switch — you test wiring precisely when the link is disarmed — but respects the effects-down check, and neither consumes nor observes the cooldown |

Public endpoints under `/api/participant/fx` (reached from the internet as
`/fx/…`):

| Method | Path | Response |
|---|---|---|
| GET | `/{token}` | `text/html` — the trigger page |
| GET | `/{token}/info` | `FxInfoResponse(tile_n, label, image_url, enabled, cooldown_seconds, ready_in_seconds, effects_up)` |
| POST | `/{token}/fire` | `FxFireResponse(fired, reason, ready_in_seconds)` |
| GET | `/{token}/image` | the tile artwork, proxied from `:55123/tiles/<path>` |

`reason` is one of `ok`, `disabled`, `cooling`, `effects-down`, `no-tile`.
A bad token is a flat 404 on every one of these, with no hint which part failed.

**State.** Four fields on `participant_state` (declare, restore in
`sync_from_restore`, emit in `snapshot`, reset in `reset`, call `persist()`
after every mutation) plus explicit fields on `PersistedSessionState`:

- `fx_enabled: bool` — **resets to `False`** every session
- `fx_token: str | None` — minted on first `GET /state`, survives the session
- `fx_tile_n: int` — default `69`
- `fx_cooldown_seconds: int` — default `10`
- `fx_last_fired_at: float | None` — wall-clock timestamp, for the host
  tooltip only. The cooldown gate reads a **monotonic** clock instead, so a
  system clock change cannot unlock the button early

**WS.** New host-only message `FxFiredMsg(tile_n, label, at)` sent through
`notify_host`, registered in `daemon/ws_messages.py` and its feature-name map
so the contract guard passes.

**Wiring.** Both routers `include_router`'d in `daemon/host_server.py`
alongside the attention routers — i.e. above the `/api/{path:path}` catch-all
reverse proxy.

### training-assistant — Railway

`railway/features/fx/router.py` (new), a pure relay:

```python
@fx_router.api_route("/fx/{path:path}", methods=["GET", "POST"])
async def fx_proxy(request: Request, path: str): ...
```

- `path` must match `^[a-z0-9/]{1,40}$`; anything else is a 404 before the
  proxy is touched. This keeps `is_safe_proxy_path` satisfied on the daemon
  side and makes the route useless as a path-traversal vector.
- The existing anti-enumeration token bucket applies.
- No `require_active_session`: the fx link is deliberately independent of
  whether a session is live. If the daemon is not connected, `proxy_to_daemon`
  already answers 503 "Trainer not connected"; the page surfaces that.
- **Registered before** the `/{session_id}` and `/{session_id}/{tab}`
  catch-alls, or it is shadowed. A test must pin the ordering.

This is the only `railway/**` change, and therefore the only real Railway
deploy the feature needs.

### training-assistant — host UI

A footer badge next to `#attention-master-badge`, following that feature's
markup and JS exactly:

- `🎛️` badge; class `connected` when armed, `disabled` when not; click toggles
  the master switch (`POST /toggle`).
- A popover holding: a checkbox mirroring the master switch; a `<select>` of
  all 91 tiles rendered `69 — scream ghost · wazzup` (tiles without a paired
  visual are marked, e.g. `· sound only`); a cooldown number input; the URL in
  a read-only field that copies on click via `_showFooterCopiedTooltip`; a
  **Rotate** button; a **Test** button.
- Buttons disable on empty input, per the project convention.
- On `FxFiredMsg` the badge pulses and its tooltip updates to
  "last fired 12s ago".
- Labels are derived from the asset filename (`69_scream_ghost.mp3` →
  `scream ghost`) when `tiles.json` supplies no `label`, since most do not.

### training-assistant — the trigger page

`static/fx.html`, served by the daemon as the body of `GET /{token}`.

Self-contained: inline CSS and JS, no external stylesheet or script, because
the page is served through the proxy and relative asset paths would resolve
under `/fx/`. The tile artwork comes from `/{token}/image`.

States: **armed** (big button, tile name and artwork), **cooling** (button
disabled with a live countdown), **disabled by host** (explanatory text, grey
button), **effects down** ("Victor's Mac is not reachable"). It polls
`/{token}/info` on a slow interval so a host toggle reaches an already-open tab.

Respects the project's no-italic rule and dark background conventions.

### training-assistant — documentation

`ARCHITECTURE.md` gains the new hop in its C4 and system-interaction diagrams:
daemon → `:55123` → `:55124` is a second, HTTP-shaped edge to the Mac apps
alongside the existing `ws://127.0.0.1:8765` bridge, and `/fx/*` is a second
public entry point at Railway alongside the participant proxy.

`backlog.md` records the feature, per the project convention for direct
requests.

## Security

- Token: 12 characters from the existing unambiguous alphabet
  `abcdefghijkmnpqrstuvwxyz123456789` (~60 bits), minted with `secrets.choice`,
  compared with `secrets.compare_digest`.
- The daemon never forwards a caller-supplied string to `:55123`. It forwards
  an **integer** it has validated against the live catalog. The Effects and
  Addons HTTP servers have no auth and bind all interfaces, so this boundary is
  what keeps an internet-facing URL from becoming a pivot into
  `/test/screenshot/crop`, `/open`, `/hands-off/*` and the rest of that route
  table.
- Two independent brakes: the master switch (off by default) and the cooldown,
  both enforced in the daemon rather than the page.
- Rotate invalidates the previous token immediately.
- Railway rate-limits `/fx/*` with the existing token bucket; the path regex
  blocks traversal before the proxy.

## Testing

- **Daemon unit tests** with `effects_client` mocked: wrong token → 404;
  disabled → `reason=disabled` and no press; inside cooldown →
  `reason=cooling` with a correct `ready_in_seconds`; unknown tile →
  `reason=no-tile`; effects down → `reason=effects-down`; happy path presses
  exactly once with the selected `n`; rotate invalidates the old token.
- **Persistence test**: the four fields round-trip through `session-state.json`
  and `fx_enabled` comes back `False` after `reset()`.
- **Railway route-ordering test**: `/fx/<token>` resolves to the fx router and
  not to the `/{session_id}/{tab}` catch-all.
- **Contract**: regenerate `docs/openapi.yaml` and `API.md` via
  `scripts/generate_apis_md.py`; the OpenAPI snapshot test must pass.
- **Swift**: a router test for `/press/<n>` asserting the four dispatched calls
  and their order, plus the unknown-tile 404.
- **Proof**: a real press end to end — open the link, hit the button, tile 69
  fires on the Mac.

## Deployment order

1. victor-effects: build, then restart — **never mid-session**, per
   `tasks/lessons.md`.
2. victor-macos-addons: `./build-app.sh` and restart, same caveat.
3. training-assistant: push to `master`. Railway redeploys because
   `railway/**` changed; the daemon hot-deploys `static/` and `daemon/` on the
   same push.
4. Verify against production: the Railway deploy must be confirmed live before
   the link is handed to anyone, since a stale Railway would answer 404.

## Out of scope

- Multiple simultaneous links, per-person links, or a menu of effects on the
  holder's page. One link, one tile, changed from the host page.
- Attribution of who fired. The link is the credential.
- A machine-readable catalog of *effect names* that have no paired tile; the
  feature addresses tiles by number, which `/tiles` already covers.
