# Secret FX Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the host a secret URL to hand to trusted people in the room; opening it shows one big button that fires a chosen soundboard tile on the trainer's Mac.

**Architecture:** Browser → Railway `/fx/<token>` (pure relay, no state) → WS `/ws/daemon` → daemon `/api/participant/fx/<token>` (token check, master switch, cooldown) → `GET http://127.0.0.1:55123/press/<n>` → addons proxy → Victor Effects `SoundboardPress.press(tile)`. The host page talks to the daemon directly over loopback, as every other host feature does.

**Tech Stack:** Swift (NWListener HTTP routers, XCTest) in two macOS repos; Python 3 + FastAPI + Pydantic + pytest in the daemon and Railway backend; plain HTML/vanilla JS (no build step) for both browser surfaces.

**Spec:** `docs/superpowers/specs/2026-09-16-fx-secret-link-design.md`

## Global Constraints

- All code, comments, variable names, commit messages and documentation in **English**.
- Daemon REST and WS payloads use **strict Pydantic models**, never raw dicts.
- Daemon logging uses `daemon/log.py`; channel `addons   ` (three trailing spaces) for anything crossing to the Mac apps, `host` for host-facing lines. Arrow geography: `addons` is horizontal-right (`→` out, `←` in), `host` is horizontal-left (`←` out, `→` in).
- Outbound WS sends must go through `daemon/ws_publish.py` (`broadcast` / `notify_host`). A guard test (`tests/test_ws_contract.py::test_no_raw_ws_sends`) fails on raw sends.
- Never edit `API.md` by hand; regenerate with `python3 scripts/generate_apis_md.py --output API.md`.
- Input + button pairs must disable the button while the input is empty or whitespace-only.
- No `font-style: italic` anywhere in the UI.
- Hide a count badge when its value is 0; never render a "0" badge.
- Railway holds no feature state — it is a dumb proxy.
- Push to `master` only. Commit after every task.
- Daemon test runs must pass `--confcutdir=tests/daemon`.
- The two Mac apps must **never** be restarted mid-live-session.

---

### Task 1: `/press/<n>` alias in Victor Effects

Adds a stable, production-named route onto the tile-press hook that already exists. Verified 2026-09-16: `GET :55124/test/thumbnail-panel/press/999` returns `{"ok":false,"n":999,"reason":"unknown-tile"}` with no panel open, so the hook needs no panel and no refactor.

**Files:**
- Modify: `/Users/victorrentea/workspace/victor-effects/Sources/VictorEffects/EffectsRouter.swift` (inside `route(forPath:)`, next to the existing `/test/thumbnail-panel/press/` block around line 205)
- Test: `/Users/victorrentea/workspace/victor-effects/Tests/VictorEffectsTests/EffectsRouterTests.swift`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /press/<n>` on port 55124, answering the JSON of `ThumbnailPanelController.pressTile(number:page:)` — `{"ok":true,"n":69,"asset":"69_scream_ghost.mp3","action":"play","durationMs":<int>}` on a hit, `{"ok":false,"n":<n>,"reason":"unknown-tile"}` at **status 200** on a miss.

- [ ] **Step 1: Write the failing test**

Append to `EffectsRouterTests.swift`:

```swift
    // MARK: - /press/<n>, the production spelling of the tile-press hook

    func testPressAliasRoutesToTheTilePressHook() {
        // The training daemon's secret FX link presses tiles by number. It must
        // not have to depend on a path spelled /test/.
        XCTAssertEqual(EffectsRouter.route(forPath: "/press/69"),
                       .panelPress(69, .effects))
    }

    func testPressAliasRejectsANonNumber() {
        XCTAssertEqual(EffectsRouter.route(forPath: "/press/wazzup"), .unknown)
    }

    func testPressAliasRejectsAnEmptyNumber() {
        XCTAssertEqual(EffectsRouter.route(forPath: "/press/"), .unknown)
    }
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/victorrentea/workspace/victor-effects && swift test --filter EffectsRouterTests
```

Expected: FAIL — `testPressAliasRoutesToTheTilePressHook` gets `.unknown` instead of `.panelPress(69, .effects)`. The two rejection tests already pass.

- [ ] **Step 3: Add the route**

In `EffectsRouter.route(forPath:)`, immediately after the existing `/test/thumbnail-panel/press/` block:

```swift
        // The production spelling of the press above. `onPanelPress` is a
        // historical name — the hook has never consulted the panel, and the
        // training daemon's secret FX link presses tiles with no panel in
        // sight. Same case, so there is one handler and nothing to drift.
        if pathOnly.hasPrefix("/press/") {
            if let n = Int(pathOnly.dropFirst("/press/".count)) {
                return .panelPress(n, .effects)
            }
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/victorrentea/workspace/victor-effects && swift test --filter EffectsRouterTests
```

Expected: PASS, all three.

- [ ] **Step 5: Run the whole Swift suite**

```bash
cd /Users/victorrentea/workspace/victor-effects && swift test 2>&1 | tail -20
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
cd /Users/victorrentea/workspace/victor-effects
git add Sources/VictorEffects/EffectsRouter.swift Tests/VictorEffectsTests/EffectsRouterTests.swift
git commit -m "Give the tile press a production path: GET /press/<n>

The training daemon is about to press tiles on behalf of the room, and
a caller outside this repo should not have to reach for a path spelled
/test/. Same hook, same handler, one more spelling."
git push
```

---

### Task 2: Forward `/press/` through Victor Addons

The daemon must reach Effects through the one door it already knows, `:55123`, so it also gets the merged `/ping` that reports `effectsUp`.

**Files:**
- Modify: `/Users/victorrentea/workspace/victor-macos-addons/Sources/VictorAddons/TabletHttpServer.swift` (the `proxiedPrefixes` array, around line 640)
- Test: `/Users/victorrentea/workspace/victor-macos-addons/Tests/VictorAddonsTests/EffectsProxyRoutingTests.swift`

**Interfaces:**
- Consumes: `GET /press/<n>` on 55124 from Task 1.
- Produces: the same route answering on `http://127.0.0.1:55123/press/<n>`.

- [ ] **Step 1: Write the failing test**

Append to `EffectsProxyRoutingTests.swift`:

```swift
    // MARK: - /press/<n>

    func testTilePressIsForwardedToTheEffectsApp() {
        // Tiles, their sounds and their paired visuals all live on 55124. The
        // training daemon presses them through this door like everything else.
        XCTAssertTrue(TabletHttpServer.isProxied("/press/69"))
    }

    func testTilePressPrefixDoesNotSwallowOtherPaths() {
        // Leading-prefix match, so nothing that merely contains "press" moves.
        XCTAssertFalse(TabletHttpServer.isProxied("/training/prompt-capture"))
    }
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/victorrentea/workspace/victor-macos-addons && swift test --filter EffectsProxyRoutingTests
```

Expected: FAIL — `testTilePressIsForwardedToTheEffectsApp` gets `false`.

- [ ] **Step 3: Add the prefix**

In `TabletHttpServer.proxiedPrefixes`, add `"/press/"` with a comment:

```swift
    static let proxiedPrefixes = ["/ping", "/sounds/", "/sound/", "/effect/",
                                  "/alarm/", "/bt-compensation", "/tiles", "/state",
                                  // The tile press counts behind the tablet's
                                  // green dots now live in the effects app, with
                                  // the panel presses they were always missing.
                                  "/usage",
                                  // Pressing a tile by number. The training
                                  // daemon uses it for the room's secret FX
                                  // link; the trailing slash keeps the match
                                  // off anything else starting with "press".
                                  "/press/"]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/victorrentea/workspace/victor-macos-addons && swift test --filter EffectsProxyRoutingTests
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/victorrentea/workspace/victor-macos-addons
git add Sources/VictorAddons/TabletHttpServer.swift Tests/VictorAddonsTests/EffectsProxyRoutingTests.swift
git commit -m "Forward /press/<n> to the effects app

One door for the training daemon: everything about tiles already answers
on 55123, and the press should not be the exception that makes a caller
learn a second port."
git push
```

---

### Task 3: `daemon/effects_client.py`

A best-effort HTTP client for the Mac apps, in the style of `daemon/addon_bridge_client.py`: short timeouts, never raises, returns `bool`/`None`.

**Files:**
- Create: `daemon/effects_client.py`
- Test: `tests/daemon/test_effects_client.py`

**Interfaces:**
- Consumes: `GET /press/<n>`, `GET /tiles`, `GET /tiles/<rel>`, `GET /ping` on `:55123` (Tasks 1–2).
- Produces:
  - `EFFECTS_BASE_URL: str`
  - `press_tile(n: int) -> bool`
  - `fetch_tiles() -> list[dict] | None` — the `tiles` array of `GET /tiles`, each item a raw dict with at least `n`, `asset`, `image`, optionally `label` and `effect`
  - `fetch_tile_image(rel_path: str) -> tuple[bytes, str] | None` — `(body, content_type)`
  - `is_up() -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_effects_client.py`:

```python
"""Tests for the Victor Effects HTTP client.

Everything here is best-effort by design: the Mac apps are allowed to be down,
and a daemon that raises because a soundboard is missing would take a workshop
with it. So every test asserts a *value*, never an exception.
"""
from unittest.mock import MagicMock, patch

from daemon import effects_client


def _response(status=200, json_body=None, content=b"", content_type="application/json"):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.content = content
    r.headers = {"content-type": content_type}
    return r


class TestPressTile:
    def test_press_calls_the_press_route_with_the_number(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "n": 69})) as g:
            assert effects_client.press_tile(69) is True
        assert g.call_args[0][0] == f"{effects_client.EFFECTS_BASE_URL}/press/69"

    def test_a_body_saying_not_ok_is_a_failure_even_at_200(self):
        """The press route reports an unknown tile in the body, not the status."""
        body = {"ok": False, "n": 999, "reason": "unknown-tile"}
        with patch("httpx.get", return_value=_response(json_body=body)):
            assert effects_client.press_tile(999) is False

    def test_a_transport_error_is_a_failure_not_an_exception(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert effects_client.press_tile(69) is False

    def test_a_non_200_is_a_failure(self):
        with patch("httpx.get", return_value=_response(status=503)):
            assert effects_client.press_tile(69) is False


class TestFetchTiles:
    def test_returns_the_tiles_array(self):
        body = {"columns": 13, "tiles": [{"n": 69, "asset": "69_scream_ghost.mp3",
                                          "image": "tiles/sfx_69.jpg", "effect": "wazzup"}]}
        with patch("httpx.get", return_value=_response(json_body=body)):
            tiles = effects_client.fetch_tiles()
        assert tiles == body["tiles"]

    def test_returns_none_when_the_effects_app_is_down(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert effects_client.fetch_tiles() is None

    def test_returns_none_when_the_body_has_no_tiles(self):
        with patch("httpx.get", return_value=_response(json_body={"error": "no tiles.json"})):
            assert effects_client.fetch_tiles() is None


class TestIsUp:
    def test_reads_effects_up_from_the_merged_ping(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "effectsUp": True})):
            assert effects_client.is_up() is True

    def test_addons_alive_but_effects_down_is_not_up(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "effectsUp": False})):
            assert effects_client.is_up() is False

    def test_unreachable_is_not_up(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert effects_client.is_up() is False


class TestFetchTileImage:
    def test_returns_body_and_content_type(self):
        r = _response(content=b"\xff\xd8jpeg", content_type="image/jpeg")
        with patch("httpx.get", return_value=r):
            assert effects_client.fetch_tile_image("tiles/sfx_69.jpg") == (b"\xff\xd8jpeg", "image/jpeg")

    def test_returns_none_when_missing(self):
        with patch("httpx.get", return_value=_response(status=404)):
            assert effects_client.fetch_tile_image("tiles/nope.jpg") is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/victorrentea/workspace/training-assistant
python3 -m pytest tests/daemon/test_effects_client.py -q --confcutdir=tests/daemon
```

Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'effects_client'`.

- [ ] **Step 3: Write the implementation**

Create `daemon/effects_client.py`:

```python
"""HTTP client for the Mac's soundboard apps.

One door: Victor Addons on :55123, which forwards everything about tiles,
sounds and effects to Victor Effects on :55124 and merges the two halves of
`/ping`. The daemon never needs to know the second port exists.

Best-effort throughout, like `addon_bridge_client`: the apps are allowed to be
closed, and nothing here may raise into a request handler.

SECURITY: `press_tile` takes an **int**. Nothing a caller types ever reaches
these URLs as a path segment — the effects ports have no authentication and
bind every interface, so keeping caller strings out of them is what stops an
internet-facing link from becoming a way to drive the trainer's Mac.
"""
import os

import httpx

from daemon import log

_NAME = "addons   "

EFFECTS_BASE_URL = os.environ.get("VICTOR_ADDONS_URL", "http://127.0.0.1:55123").rstrip("/")

# The apps are on loopback. A slow answer means something is wrong, not far.
_TIMEOUT = 2.0
# Artwork is bigger than JSON and worth a little more patience.
_IMAGE_TIMEOUT = 5.0


def press_tile(n: int) -> bool:
    """Press soundboard tile ``n`` — sound, paired visual, and its own stop.

    Returns False rather than raising when the apps are down. A miss is
    reported by the route in the *body* (``{"ok": false, "reason": ...}``) at
    status 200, so the body is what decides.
    """
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/press/{int(n)}", timeout=_TIMEOUT)
        if r.status_code != 200:
            log.info(_NAME, f"✗ press {n} (HTTP {r.status_code})")
            return False
        body = r.json()
    except Exception as e:
        log.info(_NAME, f"✗ press {n} ({type(e).__name__})")
        return False
    if not body.get("ok"):
        log.info(_NAME, f"✗ press {n} ({body.get('reason', 'refused')})")
        return False
    log.info(_NAME, f"→ press {n} ({body.get('asset', '?')})")
    return True


def fetch_tiles() -> list[dict] | None:
    """The soundboard catalog: every tile's number, asset, artwork and — where
    one is paired — the name of the visual it fires.

    Returns None when the apps are down or no manifest is mounted. Items are
    left as raw dicts on purpose: the manifest is written in the tablet's repo
    and a key added there must survive a daemon that predates it.
    """
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/tiles", timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        tiles = r.json().get("tiles")
    except Exception:
        return None
    if not isinstance(tiles, list) or not tiles:
        return None
    return tiles


def fetch_tile_image(rel_path: str) -> tuple[bytes, str] | None:
    """Artwork for one tile, addressed by its manifest-relative path.

    The path comes from the manifest the Effects app itself served, never from
    a request, so it is not a caller-controlled segment.
    """
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/tiles/{rel_path}", timeout=_IMAGE_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.content, r.headers.get("content-type", "application/octet-stream")
    except Exception:
        return None


def is_up() -> bool:
    """Is the effects app reachable and running?

    Reads ``effectsUp`` from the merged ping, so "addons is alive but effects
    is closed" reports False — which is the case that matters here.
    """
    try:
        r = httpx.get(f"{EFFECTS_BASE_URL}/ping", timeout=_TIMEOUT)
        return r.status_code == 200 and bool(r.json().get("effectsUp"))
    except Exception:
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/victorrentea/workspace/training-assistant
python3 -m pytest tests/daemon/test_effects_client.py -q --confcutdir=tests/daemon
```

Expected: PASS, 12 tests.

- [ ] **Step 5: Prove it against the real Mac apps**

```bash
cd /Users/victorrentea/workspace/training-assistant
python3 -c "
from daemon import effects_client as e
print('up:', e.is_up())
tiles = e.fetch_tiles()
print('tiles:', len(tiles or []))
print('69:', [t for t in (tiles or []) if t['n'] == 69])
print('press 999 (must be False):', e.press_tile(999))
"
```

Expected: `up: True`, `tiles: 91`, the tile-69 dict with `effect: wazzup`, and `press 999 ... False`. Do **not** press a real tile here — that makes noise; Task 12 does it deliberately.

- [ ] **Step 6: Commit**

```bash
git add daemon/effects_client.py tests/daemon/test_effects_client.py
git commit -m "Add a best-effort client for the Mac soundboard

The daemon is about to press tiles on the room's behalf. It presses by
number and never by name, so no string a participant types can reach a
port that has no authentication and listens on every interface."
git push
```

---

### Task 4: FX state on the session

Five fields, following `attention_enabled`'s five touch points exactly.

**Files:**
- Modify: `daemon/participant/state.py` (declare in `__init__` near line 64; restore in `sync_from_restore` near line 168; emit in `snapshot` near line 186; reset in `reset` near line 228)
- Modify: `daemon/persisted_models.py` (`PersistedSessionState`, near the `talk_presentation_*` fields)
- Test: `tests/daemon/test_fx_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces, on `participant_state`:
  - `fx_enabled: bool` — master switch, **False** at construction and after `reset()`
  - `fx_token: str | None` — minted lazily by Task 6, persisted
  - `fx_tile_n: int` — default `69`
  - `fx_cooldown_seconds: int` — default `10`
  - `fx_last_fired_at: float | None` — wall-clock epoch seconds, persisted, host tooltip only
  - `fx_last_fired_mono: float | None` — **not** persisted, not in `snapshot()`; the cooldown's own clock

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_fx_state.py`:

```python
"""Tests for the FX link's session state.

The master switch is OFF at construction and OFF again after reset, like the
attention bell: every session is an explicit opt-in, so yesterday's link cannot
fire into this morning's room before the host is ready.
"""
from daemon.participant.state import ParticipantState


class TestDefaults:
    def test_master_switch_starts_off(self):
        assert ParticipantState().fx_enabled is False

    def test_default_tile_is_69(self):
        assert ParticipantState().fx_tile_n == 69

    def test_default_cooldown_is_ten_seconds(self):
        assert ParticipantState().fx_cooldown_seconds == 10

    def test_no_token_until_one_is_asked_for(self):
        assert ParticipantState().fx_token is None

    def test_nothing_has_fired_yet(self):
        assert ParticipantState().fx_last_fired_at is None


class TestReset:
    def test_reset_forces_the_switch_back_off(self):
        ps = ParticipantState()
        ps.fx_enabled = True
        ps.reset()
        assert ps.fx_enabled is False

    def test_reset_drops_the_token_so_a_new_session_gets_a_new_link(self):
        ps = ParticipantState()
        ps.fx_token = "abc123def456"
        ps.reset()
        assert ps.fx_token is None

    def test_reset_returns_the_tile_to_69(self):
        ps = ParticipantState()
        ps.fx_tile_n = 3
        ps.reset()
        assert ps.fx_tile_n == 69

    def test_reset_clears_the_last_fired_stamp(self):
        ps = ParticipantState()
        ps.fx_last_fired_at = 1789554996.0
        ps.fx_last_fired_mono = 42.0
        ps.reset()
        assert ps.fx_last_fired_at is None
        assert ps.fx_last_fired_mono is None


class TestRoundTrip:
    def test_the_fields_survive_snapshot_and_restore(self):
        ps = ParticipantState()
        ps.fx_enabled = True
        ps.fx_token = "abc123def456"
        ps.fx_tile_n = 3
        ps.fx_cooldown_seconds = 30
        ps.fx_last_fired_at = 1789554996.0

        restored = ParticipantState()
        restored.sync_from_restore(ps.snapshot())

        assert restored.fx_enabled is True
        assert restored.fx_token == "abc123def456"
        assert restored.fx_tile_n == 3
        assert restored.fx_cooldown_seconds == 30
        assert restored.fx_last_fired_at == 1789554996.0

    def test_the_monotonic_stamp_is_never_persisted(self):
        """A monotonic clock means nothing in another process, so persisting it
        would let a daemon restart resurrect a cooldown from a different epoch."""
        ps = ParticipantState()
        ps.fx_last_fired_mono = 42.0
        assert "fx_last_fired_mono" not in ps.snapshot()

    def test_a_snapshot_that_omits_the_switch_leaves_it_off(self):
        """A legacy session-state.json must not accidentally arm the link."""
        restored = ParticipantState()
        restored.sync_from_restore({"mode": "workshop"})
        assert restored.fx_enabled is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 -m pytest tests/daemon/test_fx_state.py -q --confcutdir=tests/daemon
```

Expected: FAIL — `AttributeError: 'ParticipantState' object has no attribute 'fx_enabled'`.

- [ ] **Step 3: Declare the fields**

In `daemon/participant/state.py`, in `__init__` just after the `attention_enabled` block:

```python
        # ── Secret FX link ────────────────────────────────────────────────
        # A URL the host hands to two or three trusted people; opening it gives
        # them one button that presses a soundboard tile on this Mac.
        # Like the attention switch this DEFAULTS OFF and resets OFF every
        # session — a link from yesterday must not fire into this morning.
        self.fx_enabled: bool = False
        # Minted lazily the first time the host asks for the link, so a session
        # that never uses the feature never carries a credential. Persisted.
        self.fx_token: str | None = None
        # Tile 69 is the Scary Movie ghost ("wazzup"): self-terminating, loud,
        # and the one the room always asks for.
        self.fx_tile_n: int = 69
        self.fx_cooldown_seconds: int = 10
        # Wall clock, for the host's "last fired 12s ago" tooltip only.
        self.fx_last_fired_at: float | None = None
        # The cooldown's own clock. Monotonic, therefore meaningless in another
        # process — deliberately absent from snapshot() so a restart cannot
        # resurrect a cooldown measured against a different epoch.
        self.fx_last_fired_mono: float | None = None
```

In `sync_from_restore`, after the `attention_enabled` restore:

```python
            # A restore that omits the switch leaves it at its safe default (OFF).
            if isinstance(data.get("fx_enabled"), bool):
                self.fx_enabled = data["fx_enabled"]
            if isinstance(data.get("fx_token"), str) and data["fx_token"]:
                self.fx_token = data["fx_token"]
            if isinstance(data.get("fx_tile_n"), int):
                self.fx_tile_n = data["fx_tile_n"]
            if isinstance(data.get("fx_cooldown_seconds"), int):
                self.fx_cooldown_seconds = data["fx_cooldown_seconds"]
            if isinstance(data.get("fx_last_fired_at"), (int, float)):
                self.fx_last_fired_at = float(data["fx_last_fired_at"])
```

In `snapshot()`, after `"attention_enabled": self.attention_enabled,`:

```python
                "fx_enabled": self.fx_enabled,
                "fx_token": self.fx_token,
                "fx_tile_n": self.fx_tile_n,
                "fx_cooldown_seconds": self.fx_cooldown_seconds,
                "fx_last_fired_at": self.fx_last_fired_at,
```

In `reset()`, after the `attention_enabled = False` line:

```python
            # The FX link is per session: a fresh token, the default tile, and
            # the switch off until the host arms it.
            self.fx_enabled = False
            self.fx_token = None
            self.fx_tile_n = 69
            self.fx_cooldown_seconds = 10
            self.fx_last_fired_at = None
            self.fx_last_fired_mono = None
```

- [ ] **Step 4: Add the persisted-model fields**

In `daemon/persisted_models.py`, in `PersistedSessionState`, after the `talk_presentation_url` field:

```python
    # ── Secret FX link ────────────────────────────────────────────────────
    # Declared explicitly (rather than relying on PersistedModel's extra="allow")
    # so the fields survive model_dump(exclude_unset=True) in save_session_state.
    fx_enabled: bool = Field(default=False, description="Master switch for the secret FX link; resets OFF each session")
    fx_token: str | None = Field(default=None, description="Secret FX link token (CSPRNG, 12 chars)")
    fx_tile_n: int = Field(default=69, description="Soundboard tile the FX link fires")
    fx_cooldown_seconds: int = Field(default=10, description="Minimum seconds between two FX triggers")
    fx_last_fired_at: float | None = Field(default=None, description="Epoch seconds of the last FX trigger (host tooltip only)")
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_fx_state.py -q --confcutdir=tests/daemon
```

Expected: PASS, 13 tests.

- [ ] **Step 6: Run the neighbouring state tests for regressions**

```bash
python3 -m pytest tests/daemon/test_participant_state.py tests/daemon/test_daemon_state.py tests/daemon/test_attention_gate.py -q --confcutdir=tests/daemon
```

Expected: PASS, no new failures.

- [ ] **Step 7: Commit**

```bash
git add daemon/participant/state.py daemon/persisted_models.py tests/daemon/test_fx_state.py
git commit -m "Persist the FX link's state, off by default

Five fields on the session, one deliberately absent: the cooldown's
monotonic stamp never leaves this process, because a clock read against
another epoch would either unlock the button early or lock it for hours."
git push
```

---

### Task 5: The public FX endpoints

Token check, master switch, cooldown, press — plus the HTML page and the artwork proxy. This is the whole internet-facing surface.

**Files:**
- Create: `daemon/fx/__init__.py`
- Create: `daemon/fx/token.py`
- Create: `daemon/fx/router.py` (participant half only; the host half is Task 6)
- Test: `tests/daemon/test_fx_participant.py`

**Interfaces:**
- Consumes: `effects_client.press_tile / fetch_tiles / fetch_tile_image / is_up` (Task 3); `participant_state.fx_*` (Task 4).
- Produces:
  - `daemon.fx.token.FX_TOKEN_ALPHABET: str`, `FX_TOKEN_LEN: int = 12`, `generate_fx_token() -> str`
  - `daemon.fx.router.participant_router: APIRouter` on prefix `/api/participant/fx`
  - `daemon.fx.router.tile_label(tile: dict) -> str` — display name for a tile dict
  - `daemon.fx.router.find_tile(n: int) -> dict | None`
  - `FxInfoResponse(tile_n: int, label: str, effect: str | None, enabled: bool, cooldown_seconds: int, ready_in_seconds: int, effects_up: bool)`
  - `FxFireResponse(fired: bool, reason: str, ready_in_seconds: int)` where `reason ∈ {"ok","disabled","cooling","effects-down","no-tile"}`

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_fx_participant.py`:

```python
"""Tests for the public half of the secret FX link.

This is the only part of the feature reachable from the internet, so the tests
are mostly about refusal: a wrong token, a closed switch, a held-down F5, and a
Mac whose soundboard is not running.
"""
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.fx.router import participant_router
from daemon.fx.token import FX_TOKEN_ALPHABET, FX_TOKEN_LEN, generate_fx_token
from daemon.participant.state import participant_state

TOKEN = "abc123def456"
TILE_69 = {"n": 69, "asset": "69_scream_ghost.mp3",
           "image": "tiles/sfx_69_scream_ghost.jpg", "effect": "wazzup"}


@pytest.fixture(autouse=True)
def fx_state():
    participant_state.fx_enabled = True
    participant_state.fx_token = TOKEN
    participant_state.fx_tile_n = 69
    participant_state.fx_cooldown_seconds = 10
    participant_state.fx_last_fired_at = None
    participant_state.fx_last_fired_mono = None
    yield
    participant_state.fx_enabled = False
    participant_state.fx_token = None
    participant_state.fx_last_fired_mono = None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def catalog():
    with patch("daemon.fx.router.effects_client.fetch_tiles", return_value=[TILE_69]):
        yield


class TestToken:
    def test_the_alphabet_excludes_confusable_characters(self):
        for c in "oO0l":
            assert c not in FX_TOKEN_ALPHABET

    def test_a_token_is_twelve_characters_from_that_alphabet(self):
        t = generate_fx_token()
        assert len(t) == FX_TOKEN_LEN == 12
        assert set(t) <= set(FX_TOKEN_ALPHABET)

    def test_two_tokens_differ(self):
        assert generate_fx_token() != generate_fx_token()


class TestWrongToken:
    def test_the_page_is_a_flat_404(self, client):
        assert client.get("/api/participant/fx/wrongtoken12").status_code == 404

    def test_info_is_a_flat_404(self, client):
        assert client.get("/api/participant/fx/wrongtoken12/info").status_code == 404

    def test_fire_is_a_flat_404_and_presses_nothing(self, client):
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            assert client.post("/api/participant/fx/wrongtoken12/fire").status_code == 404
        press.assert_not_called()

    def test_no_token_at_all_means_every_token_is_wrong(self, client):
        participant_state.fx_token = None
        assert client.post(f"/api/participant/fx/{TOKEN}/fire").status_code == 404


class TestFire:
    def test_the_happy_path_presses_the_selected_tile_once(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.status_code == 200
        assert r.json()["fired"] is True
        assert r.json()["reason"] == "ok"
        press.assert_called_once_with(69)

    def test_a_closed_switch_refuses_without_pressing(self, client):
        participant_state.fx_enabled = False
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json() == {"fired": False, "reason": "disabled", "ready_in_seconds": 0}
        press.assert_not_called()

    def test_a_second_press_inside_the_cooldown_is_refused(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is False
        assert r.json()["reason"] == "cooling"
        assert 0 < r.json()["ready_in_seconds"] <= 10
        assert press.call_count == 1

    def test_the_cooldown_expires(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
            # Pretend the last press was 11 seconds ago on the monotonic clock.
            participant_state.fx_last_fired_mono -= 11
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_a_zero_cooldown_allows_back_to_back_presses(self, client):
        participant_state.fx_cooldown_seconds = 0
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_an_unknown_tile_is_refused_without_pressing(self, client):
        participant_state.fx_tile_n = 999
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["reason"] == "no-tile"
        press.assert_not_called()

    def test_a_failed_press_reports_effects_down_and_does_not_start_a_cooldown(self, client):
        """A press that never happened must not lock the button for ten seconds."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["reason"] == "effects-down"
        assert participant_state.fx_last_fired_mono is None


class TestInfo:
    def test_it_describes_the_selected_tile(self, client):
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        body = r.json()
        assert body["tile_n"] == 69
        assert body["label"] == "scream ghost"
        assert body["effect"] == "wazzup"
        assert body["enabled"] is True
        assert body["cooldown_seconds"] == 10
        assert body["ready_in_seconds"] == 0

    def test_it_reports_a_closed_switch_so_an_open_tab_catches_up(self, client):
        participant_state.fx_enabled = False
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        assert r.json()["enabled"] is False


class TestPage:
    def test_the_page_is_html(self, client):
        r = client.get(f"/api/participant/fx/{TOKEN}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")


class TestLabels:
    def test_a_label_is_derived_from_the_asset_filename(self):
        from daemon.fx.router import tile_label
        assert tile_label(TILE_69) == "scream ghost"

    def test_an_explicit_label_wins(self):
        from daemon.fx.router import tile_label
        assert tile_label({"n": 1, "asset": "01_baby.mp3", "label": "Baby"}) == "Baby"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 -m pytest tests/daemon/test_fx_participant.py -q --confcutdir=tests/daemon
```

Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.fx'`.

- [ ] **Step 3: Write the token helper**

Create `daemon/fx/__init__.py`:

```python
"""The secret FX link: a URL the host hands to trusted people in the room so
they can fire one soundboard tile on the trainer's Mac.

Two independent brakes, both enforced here rather than in the page: a master
switch that is off at the start of every session, and a cooldown.
"""
```

Create `daemon/fx/token.py`:

```python
"""The FX link's credential.

Same unambiguous alphabet as the join code (no `l`, `o`, `O` or `0`), because
this link gets read aloud and typed by hand too. Longer than a session id,
though: a join code is guessable by design and rate-limited to compensate,
while this one is the only thing standing between the internet and a noise in
the room.
"""
import secrets

# 33 symbols, none of them confusable in a projected or dictated URL.
FX_TOKEN_ALPHABET = "abcdefghijkmnpqrstuvwxyz123456789"
# 12 × log2(33) ≈ 60 bits.
FX_TOKEN_LEN = 12


def generate_fx_token() -> str:
    """A fresh link token from a CSPRNG."""
    return "".join(secrets.choice(FX_TOKEN_ALPHABET) for _ in range(FX_TOKEN_LEN))
```

- [ ] **Step 4: Write the participant router**

Create `daemon/fx/router.py`:

```python
"""Daemon FX router — the public half.

Everything here is reachable from the internet through Railway's `/fx/*` relay,
so it is written as a series of refusals: a wrong token is a flat 404 with no
hint which part failed, a closed master switch presses nothing, and a caller
who holds down F5 is answered with a countdown instead of a soundboard.

The press itself takes an **integer** the daemon looked up in the catalog. No
string from a request ever becomes part of a URL on the effects port.
"""
import html
import logging
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from daemon import effects_client
from daemon import log as daemon_log
from daemon.participant.state import participant_state

logger = logging.getLogger(__name__)

_PAGE_PATH = Path(__file__).resolve().parents[2] / "static" / "fx.html"


# ── Pydantic models ──

class FxInfoResponse(BaseModel):
    tile_n: int
    label: str
    effect: str | None
    enabled: bool
    cooldown_seconds: int
    ready_in_seconds: int
    effects_up: bool


class FxFireResponse(BaseModel):
    fired: bool
    # ok | disabled | cooling | effects-down | no-tile
    reason: str
    ready_in_seconds: int


# ── Helpers ──

def tile_label(tile: dict) -> str:
    """A human name for a tile.

    Most manifest rows carry no label, so the filename is the fallback:
    ``69_scream_ghost.mp3`` reads as ``scream ghost``.
    """
    explicit = (tile.get("label") or "").strip()
    if explicit:
        return explicit
    stem = str(tile.get("asset", "")).rsplit(".", 1)[0]
    _, _, rest = stem.partition("_")
    return (rest or stem).replace("_", " ")


def find_tile(n: int) -> dict | None:
    """The catalog row for tile ``n``, or None when the apps are down or the
    number is not in the manifest."""
    for tile in effects_client.fetch_tiles() or []:
        if tile.get("n") == n:
            return tile
    return None


def _check_token(token: str) -> None:
    """404 unless ``token`` is this session's link token.

    `compare_digest` so the answer's timing says nothing about how much of the
    token was right.
    """
    current = participant_state.fx_token
    if not current or not secrets.compare_digest(token, current):
        raise HTTPException(status_code=404)


def cooldown_remaining() -> int:
    """Whole seconds left before the button works again.

    Measured on a monotonic clock: a system clock that jumps must not unlock
    the button early or lock it until tomorrow.
    """
    last = participant_state.fx_last_fired_mono
    if last is None:
        return 0
    elapsed = time.monotonic() - last
    remaining = participant_state.fx_cooldown_seconds - elapsed
    return max(0, int(remaining + 0.999)) if remaining > 0 else 0


# ── Participant router ──

participant_router = APIRouter(prefix="/api/participant/fx", tags=["fx"])


@participant_router.get("/{token}", response_class=HTMLResponse)
async def fx_page(token: str):
    """The trigger page. One button, and an honest account of why it is grey."""
    _check_token(token)
    try:
        return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))
    except OSError:
        logger.error("fx page missing at %s", _PAGE_PATH)
        return HTMLResponse("<h1>FX page unavailable</h1>", status_code=500)


@participant_router.get("/{token}/info", response_model=FxInfoResponse)
async def fx_info(token: str):
    """What the page renders, and what an already-open tab polls for so a host
    toggle reaches it without a reload."""
    _check_token(token)
    n = participant_state.fx_tile_n
    tile = find_tile(n) or {}
    return FxInfoResponse(
        tile_n=n,
        label=tile_label(tile) if tile else f"tile {n}",
        effect=tile.get("effect"),
        enabled=participant_state.fx_enabled,
        cooldown_seconds=participant_state.fx_cooldown_seconds,
        ready_in_seconds=cooldown_remaining(),
        effects_up=effects_client.is_up(),
    )


@participant_router.post("/{token}/fire", response_model=FxFireResponse)
async def fx_fire(token: str):
    """Press the selected tile, if all the brakes are off."""
    _check_token(token)

    # Master switch first: a hand-crafted POST achieves nothing while closed,
    # and nothing below this line runs — no lookup, no log, no press.
    if not participant_state.fx_enabled:
        return FxFireResponse(fired=False, reason="disabled", ready_in_seconds=0)

    remaining = cooldown_remaining()
    if remaining > 0:
        return FxFireResponse(fired=False, reason="cooling", ready_in_seconds=remaining)

    n = participant_state.fx_tile_n
    tile = find_tile(n)
    if tile is None:
        return FxFireResponse(fired=False, reason="no-tile", ready_in_seconds=0)

    if not effects_client.press_tile(n):
        # A press that did not happen must not start a cooldown — otherwise a
        # closed soundboard locks the button for ten seconds per attempt.
        return FxFireResponse(fired=False, reason="effects-down", ready_in_seconds=0)

    participant_state.fx_last_fired_mono = time.monotonic()
    participant_state.fx_last_fired_at = time.time()
    participant_state.persist()

    label = tile_label(tile)
    daemon_log.info("host", f"← 🎛️ fx link fired tile {n} ({label})")

    from daemon.ws_messages import FxFiredMsg
    from daemon.ws_publish import notify_host
    await notify_host(FxFiredMsg(tile_n=n, label=label, at=participant_state.fx_last_fired_at))

    return FxFireResponse(fired=True, reason="ok",
                          ready_in_seconds=participant_state.fx_cooldown_seconds)


@participant_router.get("/{token}/image")
async def fx_image(token: str):
    """Artwork for the selected tile.

    The path handed to the effects app comes from the manifest that app served,
    never from the request — the token in the URL selects nothing but access.
    """
    _check_token(token)
    tile = find_tile(participant_state.fx_tile_n)
    if not tile or not tile.get("image"):
        raise HTTPException(status_code=404)
    fetched = effects_client.fetch_tile_image(str(tile["image"]))
    if fetched is None:
        raise HTTPException(status_code=404)
    body, content_type = fetched
    return Response(content=body, media_type=content_type,
                    headers={"Cache-Control": "no-store"})
```

Note: `FxFiredMsg` is added in Task 6; until then this import fails only when a fire succeeds. Add the message now if running tests standalone — Step 5 covers it.

- [ ] **Step 5: Add `FxFiredMsg` so the happy-path test can pass**

In `daemon/ws_messages.py`, after the attention message classes:

```python
# ── Secret FX link ────────────────────────────────────────────────────────────

class FxFiredMsg(BaseModel):
    """Host-only: someone holding the secret FX link pressed the button.

    SECURITY: carries the tile number, its display name and a timestamp — no
    token, no UUID, nothing that identifies the holder. The link is anonymous
    by design, and the host badge only needs to know that it moved.
    """
    type: Literal["fx_fired"] = "fx_fired"
    tile_n: int
    label: str
    at: float
```

Register it in `HOST_MESSAGES`:

```python
    # Secret FX link
    "fx_fired": FxFiredMsg,
```

and in `HOST_MESSAGE_FEATURES`:

```python
    # Secret FX link
    "fx_fired": "fx",
```

- [ ] **Step 6: Create the page file the router reads**

Task 7 writes the real page. Create a placeholder now so `TestPage` passes:

```bash
printf '<!doctype html><html><head><title>FX</title></head><body></body></html>\n' > static/fx.html
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_fx_participant.py -q --confcutdir=tests/daemon
```

Expected: PASS, 20 tests.

- [ ] **Step 8: Run the WS contract guard**

```bash
python3 -m pytest tests/test_ws_contract.py -q
```

Expected: PASS — `FxFiredMsg` is registered and sent through `notify_host`.

- [ ] **Step 9: Commit**

```bash
git add daemon/fx/ daemon/ws_messages.py static/fx.html tests/daemon/test_fx_participant.py
git commit -m "Open the secret FX link to the room

The only internet-facing part of the feature, written as a list of
refusals. Two of them are worth naming: a press that never reached the
Mac does not start a cooldown, and a wrong token is a flat 404 whether
the session has a link or not."
git push
```

---

### Task 6: The host's FX controls

**Files:**
- Modify: `daemon/fx/router.py` (append the host router)
- Modify: `daemon/host_server.py` (include both routers, next to the attention includes near line 271)
- Test: `tests/daemon/test_fx_host.py`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: `daemon.fx.router.host_router: APIRouter` on prefix `/api/{session_id}/host/fx` with
  - `GET /state` → `FxStateResponse(enabled, token, url, tile_n, tile_label, effect, cooldown_seconds, last_fired_at, effects_up)`
  - `GET /catalog` → `FxCatalogResponse(tiles: list[FxTile])`, `FxTile(n, label, effect, image, has_effect)`
  - `POST /toggle` → `FxStateResponse`
  - `POST /tile` with `FxTileRequest(n: int)` → `FxStateResponse`
  - `POST /cooldown` with `FxCooldownRequest(seconds: int)` → `FxStateResponse`
  - `POST /rotate` → `FxStateResponse`
  - `POST /test` → `FxFireResponse`

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_fx_host.py`:

```python
"""Tests for the host's FX controls.

The host page is served over loopback, so there is no auth here — the tests are
about behaviour: the link is minted lazily, rotation invalidates the old one,
and the host's own Test button works precisely when the link is disarmed.
"""
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.fx.router import host_router, participant_router
from daemon.participant.state import participant_state

TILE_69 = {"n": 69, "asset": "69_scream_ghost.mp3",
           "image": "tiles/sfx_69_scream_ghost.jpg", "effect": "wazzup"}
TILE_1 = {"n": 1, "asset": "01_baby.mp3", "image": "tiles/sfx_01_baby.jpg"}


@pytest.fixture(autouse=True)
def fx_state():
    participant_state.fx_enabled = False
    participant_state.fx_token = None
    participant_state.fx_tile_n = 69
    participant_state.fx_cooldown_seconds = 10
    participant_state.fx_last_fired_at = None
    participant_state.fx_last_fired_mono = None
    yield
    participant_state.fx_enabled = False
    participant_state.fx_token = None


@pytest.fixture(autouse=True)
def no_persist():
    with patch("daemon.participant.state.ParticipantState.persist"):
        yield


@pytest.fixture(autouse=True)
def catalog():
    with patch("daemon.fx.router.effects_client.fetch_tiles", return_value=[TILE_1, TILE_69]), \
         patch("daemon.fx.router.effects_client.is_up", return_value=True):
        yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(host_router)
    app.include_router(participant_router)
    return TestClient(app)


class TestState:
    def test_the_first_read_mints_a_token(self, client):
        assert participant_state.fx_token is None
        body = client.get("/api/cur/host/fx/state").json()
        assert len(body["token"]) == 12
        assert participant_state.fx_token == body["token"]

    def test_a_second_read_keeps_the_same_token(self, client):
        first = client.get("/api/cur/host/fx/state").json()["token"]
        assert client.get("/api/cur/host/fx/state").json()["token"] == first

    def test_the_url_is_the_short_public_form(self, client):
        with patch.dict("os.environ", {"WORKSHOP_SERVER_URL": "https://interact.victorrentea.ro"}):
            body = client.get("/api/cur/host/fx/state").json()
        assert body["url"] == f"https://interact.victorrentea.ro/fx/{body['token']}"

    def test_it_names_the_selected_tile(self, client):
        body = client.get("/api/cur/host/fx/state").json()
        assert body["tile_n"] == 69
        assert body["tile_label"] == "scream ghost"
        assert body["effect"] == "wazzup"


class TestCatalog:
    def test_it_lists_every_tile_with_a_label(self, client):
        tiles = client.get("/api/cur/host/fx/catalog").json()["tiles"]
        assert [t["n"] for t in tiles] == [1, 69]
        assert tiles[1]["label"] == "scream ghost"

    def test_it_marks_which_tiles_animate_the_screen(self, client):
        tiles = client.get("/api/cur/host/fx/catalog").json()["tiles"]
        assert tiles[0]["has_effect"] is False
        assert tiles[1]["has_effect"] is True

    def test_a_missing_soundboard_is_an_empty_catalog_not_a_crash(self, client):
        with patch("daemon.fx.router.effects_client.fetch_tiles", return_value=None):
            r = client.get("/api/cur/host/fx/catalog")
        assert r.status_code == 200
        assert r.json()["tiles"] == []


class TestToggle:
    def test_it_flips_the_switch(self, client):
        assert client.post("/api/cur/host/fx/toggle").json()["enabled"] is True
        assert participant_state.fx_enabled is True
        assert client.post("/api/cur/host/fx/toggle").json()["enabled"] is False


class TestTile:
    def test_it_selects_a_tile_from_the_catalog(self, client):
        assert client.post("/api/cur/host/fx/tile", json={"n": 1}).json()["tile_n"] == 1
        assert participant_state.fx_tile_n == 1

    def test_a_tile_outside_the_catalog_is_refused(self, client):
        r = client.post("/api/cur/host/fx/tile", json={"n": 999})
        assert r.status_code == 404
        assert participant_state.fx_tile_n == 69


class TestCooldown:
    def test_it_sets_the_cooldown(self, client):
        assert client.post("/api/cur/host/fx/cooldown", json={"seconds": 30}).json()["cooldown_seconds"] == 30

    def test_a_negative_cooldown_is_rejected(self, client):
        assert client.post("/api/cur/host/fx/cooldown", json={"seconds": -1}).status_code == 422

    def test_an_absurd_cooldown_is_rejected(self, client):
        assert client.post("/api/cur/host/fx/cooldown", json={"seconds": 3600}).status_code == 422


class TestRotate:
    def test_rotation_changes_the_token(self, client):
        old = client.get("/api/cur/host/fx/state").json()["token"]
        new = client.post("/api/cur/host/fx/rotate").json()["token"]
        assert new != old

    def test_the_old_link_stops_working_immediately(self, client):
        old = client.get("/api/cur/host/fx/state").json()["token"]
        client.post("/api/cur/host/fx/rotate")
        assert client.post(f"/api/participant/fx/{old}/fire").status_code == 404


class TestHostTestButton:
    def test_it_fires_even_while_the_link_is_disarmed(self, client):
        """You test the wiring precisely when the link is not live."""
        assert participant_state.fx_enabled is False
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            r = client.post("/api/cur/host/fx/test")
        assert r.json()["fired"] is True
        press.assert_called_once_with(69)

    def test_it_ignores_the_cooldown(self, client):
        participant_state.fx_cooldown_seconds = 300
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post("/api/cur/host/fx/test")
            r = client.post("/api/cur/host/fx/test")
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_it_does_not_start_a_cooldown_for_the_room(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
            client.post("/api/cur/host/fx/test")
        assert participant_state.fx_last_fired_mono is None

    def test_it_still_reports_a_closed_soundboard(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            assert client.post("/api/cur/host/fx/test").json()["reason"] == "effects-down"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 -m pytest tests/daemon/test_fx_host.py -q --confcutdir=tests/daemon
```

Expected: FAIL — `ImportError: cannot import name 'host_router' from 'daemon.fx.router'`.

- [ ] **Step 3: Append the host router**

Add to the top of `daemon/fx/router.py`:

```python
import os
```

and append at the end of the file:

```python
# ── Host router (called directly on daemon loopback, like the attention host router) ──

class FxTile(BaseModel):
    n: int
    label: str
    effect: str | None
    image: str
    has_effect: bool


class FxCatalogResponse(BaseModel):
    tiles: list[FxTile]


class FxStateResponse(BaseModel):
    enabled: bool
    token: str
    url: str
    tile_n: int
    tile_label: str
    effect: str | None
    cooldown_seconds: int
    last_fired_at: float | None
    effects_up: bool


class FxTileRequest(BaseModel):
    n: int


class FxCooldownRequest(BaseModel):
    # Five minutes is already absurd for a party trick; the cap keeps a typo
    # from parking the button for the rest of the workshop.
    seconds: int = Field(ge=0, le=300)


host_router = APIRouter(prefix="/api/{session_id}/host/fx", tags=["fx"])


def _public_base_url() -> str:
    """Where participants reach this workshop. Same source as the join link."""
    return os.environ.get("WORKSHOP_SERVER_URL", "http://localhost:8000").rstrip("/")


def _ensure_token() -> str:
    """This session's link token, minted on first use.

    Lazy so a session that never opens the popover never carries a credential.
    """
    if not participant_state.fx_token:
        participant_state.fx_token = generate_fx_token()
        participant_state.persist()
    return participant_state.fx_token


def _state_response() -> FxStateResponse:
    token = _ensure_token()
    n = participant_state.fx_tile_n
    tile = find_tile(n) or {}
    return FxStateResponse(
        enabled=participant_state.fx_enabled,
        token=token,
        url=f"{_public_base_url()}/fx/{token}",
        tile_n=n,
        tile_label=tile_label(tile) if tile else f"tile {n}",
        effect=tile.get("effect"),
        cooldown_seconds=participant_state.fx_cooldown_seconds,
        last_fired_at=participant_state.fx_last_fired_at,
        effects_up=effects_client.is_up(),
    )


@host_router.get("/state", response_model=FxStateResponse)
async def fx_state():
    """Everything the footer badge and its popover render."""
    return _state_response()


@host_router.get("/catalog", response_model=FxCatalogResponse)
async def fx_catalog():
    """The 91 tiles, read live from the Mac.

    Built at request time rather than kept in a list here: adding a tile is a
    JSON entry plus an image in another repo, and a hand-maintained copy would
    be wrong by the next workshop. A closed soundboard is an empty catalog, not
    an error — the popover says so itself.
    """
    tiles = effects_client.fetch_tiles() or []
    return FxCatalogResponse(tiles=[
        FxTile(
            n=int(t.get("n", 0)),
            label=tile_label(t),
            effect=t.get("effect"),
            image=str(t.get("image", "")),
            has_effect=bool(t.get("effect")),
        )
        for t in tiles if isinstance(t.get("n"), int)
    ])


@host_router.post("/toggle", response_model=FxStateResponse)
async def fx_toggle():
    """Arm or disarm the link. Off at the start of every session."""
    participant_state.fx_enabled = not participant_state.fx_enabled
    participant_state.persist()
    daemon_log.info("host", f"🎛️ fx link {'armed' if participant_state.fx_enabled else 'disarmed'}")
    return _state_response()


@host_router.post("/tile", response_model=FxStateResponse)
async def fx_set_tile(body: FxTileRequest):
    """Bind the link to a different tile."""
    if find_tile(body.n) is None:
        raise HTTPException(status_code=404, detail="Unknown tile")
    participant_state.fx_tile_n = body.n
    participant_state.persist()
    daemon_log.info("host", f"🎛️ fx link now fires tile {body.n}")
    return _state_response()


@host_router.post("/cooldown", response_model=FxStateResponse)
async def fx_set_cooldown(body: FxCooldownRequest):
    """Change how often the room may pull the lever."""
    participant_state.fx_cooldown_seconds = body.seconds
    participant_state.persist()
    return _state_response()


@host_router.post("/rotate", response_model=FxStateResponse)
async def fx_rotate():
    """Mint a new token, killing the current link immediately."""
    participant_state.fx_token = generate_fx_token()
    participant_state.fx_last_fired_mono = None
    participant_state.persist()
    daemon_log.info("host", "🎛️ fx link rotated — the old URL is dead")
    return _state_response()


@host_router.post("/test", response_model=FxFireResponse)
async def fx_test():
    """Fire the selected tile from the host page.

    Deliberately ignores both brakes: you check the wiring precisely when the
    link is disarmed, and a cooldown meant for the room should not make the
    trainer wait. It does not start a cooldown either — testing must not take
    the lever away from someone holding the link.
    """
    tile = find_tile(participant_state.fx_tile_n)
    if tile is None:
        return FxFireResponse(fired=False, reason="no-tile", ready_in_seconds=0)
    if not effects_client.press_tile(participant_state.fx_tile_n):
        return FxFireResponse(fired=False, reason="effects-down", ready_in_seconds=0)
    return FxFireResponse(fired=True, reason="ok", ready_in_seconds=0)
```

Update the imports at the top of `daemon/fx/router.py`:

```python
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from daemon.fx.token import generate_fx_token
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_fx_host.py -q --confcutdir=tests/daemon
```

Expected: PASS, 18 tests.

- [ ] **Step 5: Mount both routers in the daemon app**

In `daemon/host_server.py`, beside the attention includes:

```python
    from daemon.fx.router import host_router as fx_host_router
    from daemon.fx.router import participant_router as fx_participant_router
    app.include_router(fx_participant_router)  # /api/participant/fx/*  (reached from the internet as /fx/*)
    app.include_router(fx_host_router)         # /api/{session_id}/host/fx/*
```

- [ ] **Step 6: Run the daemon suite**

```bash
bash tests/run-daemon-tests.sh
```

Expected: PASS, no new failures.

- [ ] **Step 7: Commit**

```bash
git add daemon/fx/router.py daemon/host_server.py tests/daemon/test_fx_host.py
git commit -m "Give the host the FX link's controls

The catalog is read live from the Mac rather than kept here, because a
tile is a JSON entry in another repo and a copy of the list would be
wrong by the next workshop."
git push
```

---

### Task 7: The trigger page

**Files:**
- Modify: `static/fx.html` (replace the Task 5 placeholder)
- Test: manual, in a browser, against the running daemon

**Interfaces:**
- Consumes: `GET /fx/<token>/info`, `POST /fx/<token>/fire`, `GET /fx/<token>/image` (Task 5), all relative to the page's own URL.
- Produces: nothing other code depends on.

- [ ] **Step 1: Write the page**

Replace `static/fx.html` entirely:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<title>Pull the lever</title>
<style>
  /* Self-contained on purpose: this page is served through the Railway proxy,
     where a relative stylesheet path would resolve under /fx/ and 404. */
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100dvh; padding: 24px 16px;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px;
    background: #14121a; color: #f2eef8;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    text-align: center; overflow-x: hidden;
  }
  #art {
    width: 140px; height: 140px; border-radius: 20px; object-fit: cover;
    border: 2px solid #3a3350; background: #1d1a26; display: none;
  }
  #label { font-size: 1.4rem; font-weight: 700; letter-spacing: .01em; }
  #num { font-size: .8rem; color: #9a90b4; letter-spacing: .14em; text-transform: uppercase; }
  #fire {
    width: min(78vw, 300px); height: min(78vw, 300px); border-radius: 50%; border: none;
    font-size: 1.5rem; font-weight: 800; letter-spacing: .02em; color: #fff; cursor: pointer;
    background: radial-gradient(circle at 32% 28%, #ff6b5e, #c62f4a 62%, #8d1030);
    box-shadow: 0 16px 40px rgba(198,47,74,.42), inset 0 -8px 20px rgba(0,0,0,.35);
    transition: transform .08s ease, filter .15s ease;
    -webkit-tap-highlight-color: transparent;
  }
  #fire:active:not(:disabled) { transform: scale(.95); }
  #fire:disabled { cursor: not-allowed; filter: grayscale(.85) brightness(.55); box-shadow: none; }
  #fire.flash { animation: pop .45s ease; }
  @keyframes pop {
    0% { transform: scale(1); } 35% { transform: scale(1.09); } 100% { transform: scale(1); }
  }
  #status { min-height: 1.5em; font-size: .95rem; color: #b8aed2; max-width: 30rem; }
  #status.bad { color: #ff9b8f; }
</style>
</head>
<body>
  <img id="art" alt="">
  <div>
    <div id="num"></div>
    <div id="label">…</div>
  </div>
  <button id="fire" disabled>…</button>
  <div id="status">Loading…</div>

<script>
(function () {
  // The page's own URL is the base: /fx/<token>. Everything hangs off it, so
  // the token never has to be parsed out or stored anywhere.
  const BASE = location.pathname.replace(/\/+$/, '');
  const btn = document.getElementById('fire');
  const label = document.getElementById('label');
  const num = document.getElementById('num');
  const art = document.getElementById('art');
  const status = document.getElementById('status');

  let ready = 0;          // seconds left on the cooldown
  let enabled = false;
  let effectsUp = true;
  let firing = false;

  function say(text, bad) {
    status.textContent = text;
    status.classList.toggle('bad', !!bad);
  }

  function render() {
    if (!enabled) {
      btn.disabled = true;
      btn.textContent = 'OFF';
      say('The host has switched the effects off right now. Your link still works — keep this tab open.');
      return;
    }
    if (!effectsUp) {
      btn.disabled = true;
      btn.textContent = 'OFF';
      say('The soundboard on the trainer’s Mac is not reachable.', true);
      return;
    }
    if (ready > 0) {
      btn.disabled = true;
      btn.textContent = ready + 's';
      say('Cooling down — everyone shares one lever.');
      return;
    }
    btn.disabled = firing;
    btn.textContent = firing ? '…' : 'FIRE';
    if (!firing) say('Press it when the room needs waking up.');
  }

  function applyInfo(info) {
    enabled = !!info.enabled;
    effectsUp = !!info.effects_up;
    ready = info.ready_in_seconds || 0;
    label.textContent = info.label || ('tile ' + info.tile_n);
    num.textContent = '#' + info.tile_n + (info.effect ? ' · ' + info.effect : '');
    document.title = label.textContent;
    art.src = BASE + '/image?v=' + info.tile_n;
    art.style.display = 'block';
    art.onerror = function () { art.style.display = 'none'; };
    render();
  }

  async function loadInfo() {
    try {
      const r = await fetch(BASE + '/info', { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      applyInfo(await r.json());
    } catch (e) {
      say('Cannot reach the workshop right now.', true);
      btn.disabled = true;
      btn.textContent = '—';
    }
  }

  async function fire() {
    if (btn.disabled || firing) return;
    firing = true; render();
    try {
      const r = await fetch(BASE + '/fire', { method: 'POST' });
      if (!r.ok) throw new Error(r.status);
      const res = await r.json();
      firing = false;
      ready = res.ready_in_seconds || 0;
      if (res.fired) {
        btn.classList.remove('flash');
        void btn.offsetWidth;   // restart the animation
        btn.classList.add('flash');
        render();
        say('Fired 💥');
      } else if (res.reason === 'disabled') {
        enabled = false; render();
      } else if (res.reason === 'effects-down') {
        effectsUp = false; render();
      } else {
        render();
      }
    } catch (e) {
      firing = false;
      say('That did not get through. Try again.', true);
      render();
    }
  }

  btn.addEventListener('click', fire);

  // One tick drives the countdown; every fifth tick also re-reads the server,
  // so a host toggle reaches a tab that has been open since the coffee break.
  let tick = 0;
  setInterval(function () {
    if (ready > 0) { ready -= 1; render(); }
    if (++tick % 5 === 0 && !firing) loadInfo();
  }, 1000);

  loadInfo();
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the page loads against the running daemon**

```bash
cd /Users/victorrentea/workspace/training-assistant
TOKEN=$(curl -s localhost:1234/api/cur/host/fx/state | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
echo "token: $TOKEN"
curl -s -o /dev/null -w "page %{http_code} %{content_type}\n" "localhost:1234/api/participant/fx/$TOKEN"
curl -s "localhost:1234/api/participant/fx/$TOKEN/info"; echo
curl -s -o /dev/null -w "image %{http_code} %{content_type}\n" "localhost:1234/api/participant/fx/$TOKEN/image"
```

Expected: `page 200 text/html`, an info JSON naming tile 69 `scream ghost` / `wazzup`, and `image 200 image/jpeg`.

- [ ] **Step 3: Look at it in a browser**

Open `http://localhost:1234/api/participant/fx/$TOKEN` and confirm: the ghost artwork, `#69 · wazzup`, and a grey `OFF` button (the switch is off by default). Arm it with `curl -s -X POST localhost:1234/api/cur/host/fx/toggle` and confirm the button turns red within five seconds **without a reload**. Capture a screenshot for the user, per the project's proof-before-done rule.

- [ ] **Step 4: Commit**

```bash
git add static/fx.html
git commit -m "Give the link holder a page worth keeping open

One button, and an honest reason whenever it is grey: off, cooling, or
a Mac that is not answering. It re-reads the server every five seconds
so a host toggle reaches a tab opened before the coffee break."
git push
```

---

### Task 8: The host's footer badge

**Files:**
- Modify: `static/host.html` (after `#attention-notify-wrap`, inside `.host-footer-left`, around line 364)
- Modify: `static/host.js` (beside the attention functions, around line 935; WS dispatch where other host messages are handled)
- Test: manual, plus the existing JS unit suite

**Interfaces:**
- Consumes: `API('/fx/state' | '/fx/catalog' | '/fx/toggle' | '/fx/tile' | '/fx/cooldown' | '/fx/rotate' | '/fx/test')` (Task 6); the `fx_fired` host WS message (Task 5).
- Produces: nothing other code depends on.

- [ ] **Step 1: Add the markup**

In `static/host.html`, immediately after the closing `</div>` of `#attention-notify-wrap`:

```html
    <div id="fx-wrap" style="position:relative;">
      <span id="fx-badge" class="badge disabled footer-tooltip-target" onclick="toggleFxPopover(event)" style="cursor:pointer; font-size:1rem;">🎛️</span>
      <div id="fx-popover" style="display:none; position:absolute; bottom:calc(100% + 8px); left:0;
           background:var(--surface2); border:1px solid var(--color-primary,#6750a4); border-radius:8px;
           padding:.6rem .7rem; white-space:nowrap; z-index:300; box-shadow:0 4px 14px rgba(0,0,0,.45);">
        <label style="display:flex; gap:.45rem; align-items:center; font-size:.85rem; cursor:pointer; margin-bottom:.5rem;">
          <input id="fx-enabled" type="checkbox" onchange="toggleFxEnabled()" style="cursor:pointer;">
          Let the link fire effects
        </label>
        <div style="display:flex; gap:.4rem; align-items:center; margin-bottom:.5rem;">
          <select id="fx-tile" onchange="setFxTile()"
                  style="width:17rem; padding:.35rem .5rem; border-radius:5px; border:1px solid var(--outline,#555);
                         background:var(--surface,#1e1e1e); color:var(--text,#fff); font-size:.85rem;"></select>
          <input id="fx-cooldown" type="number" min="0" max="300" title="Seconds between triggers"
                 onchange="setFxCooldown()"
                 style="width:4.2rem; padding:.35rem .4rem; border-radius:5px; border:1px solid var(--outline,#555);
                        background:var(--surface,#1e1e1e); color:var(--text,#fff); font-size:.85rem;">
        </div>
        <div style="display:flex; gap:.4rem; align-items:center;">
          <input id="fx-url" type="text" readonly onclick="copyFxLink(this)" title="Click to copy"
                 style="width:17rem; padding:.35rem .55rem; border-radius:5px; border:1px solid var(--outline,#555);
                        background:var(--surface,#1e1e1e); color:var(--text,#fff); font-size:.8rem; cursor:pointer;">
          <button id="fx-test-btn" onclick="testFx()"
                  style="padding:.35rem .7rem; border:none; border-radius:5px; background:var(--color-primary,#6750a4);
                         color:#fff; cursor:pointer; font-size:.85rem; font-weight:600;">Test</button>
          <button id="fx-rotate-btn" onclick="rotateFxLink()" title="Kill this link and mint a new one"
                  style="padding:.35rem .7rem; border:1px solid var(--outline,#555); border-radius:5px;
                         background:transparent; color:var(--text,#fff); cursor:pointer; font-size:.85rem;">Rotate</button>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Add the JavaScript**

In `static/host.js`, after `sendHostNotification()`:

```js
  // ── Secret FX link ────────────────────────────────────────────────────────
  // The badge is the switch, like 🔔 next door; the popover is where the link
  // and the tile live. Its state always comes from the daemon's answer, never
  // from what the click assumed.

  let _fxCatalogLoaded = false;

  function applyFxState(s) {
    const badge = document.getElementById('fx-badge');
    if (badge) {
      badge.classList.toggle('connected', !!s.enabled);
      badge.classList.toggle('disabled', !s.enabled);
      const fired = s.last_fired_at
        ? ' · last fired ' + _fxAgo(s.last_fired_at)
        : '';
      badge.title = (s.enabled ? 'FX link armed' : 'FX link off')
        + ' · #' + s.tile_n + ' ' + s.tile_label + fired;
    }
    const cb = document.getElementById('fx-enabled');
    if (cb) cb.checked = !!s.enabled;
    const url = document.getElementById('fx-url');
    if (url) url.value = s.url || '';
    const cd = document.getElementById('fx-cooldown');
    if (cd && document.activeElement !== cd) cd.value = s.cooldown_seconds;
    const sel = document.getElementById('fx-tile');
    if (sel && sel.options.length) sel.value = String(s.tile_n);
  }

  function _fxAgo(epochSeconds) {
    const secs = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
    if (secs < 60) return secs + 's ago';
    if (secs < 3600) return Math.round(secs / 60) + 'm ago';
    return Math.round(secs / 3600) + 'h ago';
  }

  async function loadFxState() {
    try {
      applyFxState(await (await fetch(API('/fx/state'))).json());
    } catch (e) {
      console.error('fx state load failed', e);
    }
  }

  async function loadFxCatalog() {
    if (_fxCatalogLoaded) return;
    const sel = document.getElementById('fx-tile');
    if (!sel) return;
    try {
      const { tiles } = await (await fetch(API('/fx/catalog'))).json();
      sel.innerHTML = '';
      if (!tiles.length) {
        sel.innerHTML = '<option>— soundboard not reachable —</option>';
        return;
      }
      for (const t of tiles) {
        const o = document.createElement('option');
        o.value = String(t.n);
        o.textContent = t.n + ' — ' + t.label + (t.effect ? ' · ' + t.effect : ' · sound only');
        sel.appendChild(o);
      }
      _fxCatalogLoaded = true;
      await loadFxState();   // re-select the current tile now that options exist
    } catch (e) {
      console.error('fx catalog load failed', e);
    }
  }

  function toggleFxPopover(ev) {
    if (ev) ev.stopPropagation();
    const pop = document.getElementById('fx-popover');
    if (!pop) return;
    const showing = pop.style.display !== 'none';
    pop.style.display = showing ? 'none' : 'block';
    if (!showing) { loadFxCatalog(); loadFxState(); }
  }

  async function toggleFxEnabled() {
    try {
      applyFxState(await (await fetch(API('/fx/toggle'), { method: 'POST' })).json());
    } catch (e) {
      console.error('fx toggle failed', e);
      loadFxState();
    }
  }

  async function setFxTile() {
    const sel = document.getElementById('fx-tile');
    if (!sel) return;
    try {
      const r = await fetch(API('/fx/tile'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ n: Number(sel.value) })
      });
      if (!r.ok) throw new Error(r.status);
      applyFxState(await r.json());
    } catch (e) {
      console.error('fx tile set failed', e);
      loadFxState();
    }
  }

  async function setFxCooldown() {
    const inp = document.getElementById('fx-cooldown');
    if (!inp) return;
    const seconds = Math.max(0, Math.min(300, Number(inp.value) || 0));
    try {
      const r = await fetch(API('/fx/cooldown'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds })
      });
      if (!r.ok) throw new Error(r.status);
      applyFxState(await r.json());
    } catch (e) {
      console.error('fx cooldown set failed', e);
      loadFxState();
    }
  }

  function copyFxLink(el) {
    if (!el || !el.value) return;
    navigator.clipboard.writeText(el.value)
      .then(() => _showFooterCopiedTooltip(el, 'Link copied'))
      .catch((e) => console.error('fx link copy failed', e));
  }

  async function rotateFxLink() {
    try {
      applyFxState(await (await fetch(API('/fx/rotate'), { method: 'POST' })).json());
      const el = document.getElementById('fx-url');
      if (el) _showFooterCopiedTooltip(el, 'New link — the old one is dead');
    } catch (e) {
      console.error('fx rotate failed', e);
    }
  }

  async function testFx() {
    const btn = document.getElementById('fx-test-btn');
    if (btn) btn.disabled = true;
    try {
      const res = await (await fetch(API('/fx/test'), { method: 'POST' })).json();
      if (!res.fired && btn) btn.textContent = res.reason === 'effects-down' ? 'No Mac' : 'No tile';
      setTimeout(() => { if (btn) btn.textContent = 'Test'; }, 2000);
    } catch (e) {
      console.error('fx test failed', e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function flashFxBadge(msg) {
    const badge = document.getElementById('fx-badge');
    if (!badge) return;
    badge.style.transition = 'transform .18s ease';
    badge.style.transform = 'scale(1.35)';
    setTimeout(() => { badge.style.transform = ''; }, 200);
    badge.title = 'FX link armed · #' + msg.tile_n + ' ' + msg.label + ' · last fired just now';
  }
```

- [ ] **Step 3: Wire the WS message and the initial load**

In `static/host.js`, in the host WS message dispatch (where `bell_rung` and the other host messages are handled), add:

```js
      } else if (msg.type === 'fx_fired') {
        flashFxBadge(msg);
```

and call `loadFxState();` in the same initialisation block that primes the other footer badges on page load.

- [ ] **Step 4: Run the JS unit tests**

```bash
cd /Users/victorrentea/workspace/training-assistant && node tests/test_js_unit.js
```

Expected: PASS, no new failures.

- [ ] **Step 5: Verify in the browser**

Open `http://localhost:8081/` (the host page), click 🎛️, and confirm: the popover lists 91 tiles with `69 — scream ghost · wazzup` selected, the URL field copies on click, the checkbox arms the badge, `Test` fires the ghost on the Mac, and `Rotate` changes the URL. Screenshot for the user.

- [ ] **Step 6: Commit**

```bash
git add static/host.html static/host.js
git commit -m "Put the FX link in the host footer, next to the bell

The badge is the switch and the popover is the rest, because this is a
lever the host reaches for mid-sentence and a tab would be a detour."
git push
```

---

### Task 9: The Railway relay

The only `railway/**` change, and therefore the only real Railway deploy this feature needs.

**Files:**
- Create: `railway/features/fx/__init__.py`
- Create: `railway/features/fx/router.py`
- Modify: `railway/app.py` (register **before** the catch-alls at the end of the file)
- Test: `tests/test_fx_railway.py`

**Interfaces:**
- Consumes: `railway.features.ws.proxy_bridge.proxy_to_daemon(method, path, body, headers, participant_id)`.
- Produces: public `GET`/`POST` `https://interact.victorrentea.ro/fx/{path}` → daemon `/api/participant/fx/{path}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fx_railway.py`:

```python
"""Tests for the public /fx/* relay.

Two things are load-bearing here and both have bitten this repo before: the
route must be registered before the /{session_id}/{tab} catch-all, and the path
must be constrained before it reaches a proxy that resolves `../` at the far
end.
"""
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

from railway.app import app

client = TestClient(app)


@pytest.fixture
def proxy():
    with patch("railway.features.fx.router.proxy_to_daemon", new_callable=AsyncMock) as p:
        p.return_value = "relayed"
        yield p


class TestRelay:
    def test_a_get_reaches_the_daemon_under_the_participant_prefix(self, proxy):
        client.get("/fx/abc123def456")
        assert proxy.await_args.kwargs["path"] == "/api/participant/fx/abc123def456"
        assert proxy.await_args.kwargs["method"] == "GET"

    def test_a_post_to_fire_is_relayed(self, proxy):
        client.post("/fx/abc123def456/fire")
        assert proxy.await_args.kwargs["path"] == "/api/participant/fx/abc123def456/fire"
        assert proxy.await_args.kwargs["method"] == "POST"

    def test_the_image_subpath_is_relayed(self, proxy):
        client.get("/fx/abc123def456/image")
        assert proxy.await_args.kwargs["path"] == "/api/participant/fx/abc123def456/image"


class TestPathConstraint:
    @pytest.mark.parametrize("bad", [
        "/fx/../../etc/passwd",
        "/fx/%2e%2e/secret",
        "/fx/ABC123",
        "/fx/abc-123",
        "/fx/abc.123",
        "/fx/" + "a" * 41,
    ])
    def test_a_path_outside_the_alphabet_never_reaches_the_daemon(self, proxy, bad):
        r = client.get(bad)
        assert r.status_code == 404
        proxy.assert_not_awaited()

    def test_an_empty_token_is_refused(self, proxy):
        assert client.get("/fx/").status_code == 404
        proxy.assert_not_awaited()


class TestRouteOrdering:
    def test_fx_is_not_swallowed_by_the_session_catch_all(self, proxy):
        """/{session_id}/{tab} matches any two-segment path. If the fx router is
        registered after it, /fx/<token> becomes session "fx", tab "<token>"."""
        client.get("/fx/abc123def456")
        proxy.assert_awaited_once()

    def test_the_session_catch_all_still_works(self):
        """Registering earlier must not shadow ordinary participant pages."""
        r = client.get("/notasession/quiz")
        assert r.status_code in (302, 404)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/victorrentea/workspace/training-assistant && python3 -m pytest tests/test_fx_railway.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'railway.features.fx'`.

- [ ] **Step 3: Write the relay**

Create `railway/features/fx/__init__.py` (empty) and `railway/features/fx/router.py`:

```python
"""Public relay for the secret FX link.

A path prefix and nothing else: no token is checked here, no tile is known
here, no state is kept here. The daemon on the trainer's Mac owns all of it,
and this backend stays the dumb proxy it is everywhere else.

The path IS constrained, though. `proxy_to_daemon` hands the string to an httpx
call at the far end, where `../` is resolved against the daemon's own base URL —
so the alphabet is pinned here, before the string can travel.
"""
import re

from fastapi import APIRouter, HTTPException, Request

from railway.features.ws.proxy_bridge import proxy_to_daemon

fx_router = APIRouter()

# The FX token's alphabet plus the two subpaths that hang off it. Anything
# else — uppercase, dots, percent-escapes, slashes beyond one level — is not a
# link this feature ever minted.
_FX_PATH = re.compile(r"^[a-z0-9]{1,24}(/(info|fire|image))?$")


@fx_router.api_route("/fx/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def fx_relay(request: Request, path: str):
    """Relay /fx/* to the daemon's /api/participant/fx/*."""
    if not _FX_PATH.match(path):
        raise HTTPException(status_code=404)
    return await proxy_to_daemon(
        method=request.method,
        path=f"/api/participant/fx/{path}",
        body=await request.body(),
        headers=dict(request.headers),
        participant_id=None,
    )
```

- [ ] **Step 4: Register it before the catch-alls**

In `railway/app.py`, immediately **above** the `# ── Catch-all participant routes — registered ABSOLUTELY LAST ──` comment:

```python
# The room's secret FX link. Two segments (/fx/<token>), so it MUST be
# registered before /{session_id}/{tab} below or that catch-all reads it as
# session "fx", tab "<token>". Public and session-independent by design: the
# link is handed out ahead of time and must not die between sessions.
from railway.features.fx.router import fx_router
app.include_router(fx_router, dependencies=[Depends(rate_limit_probe)])
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 -m pytest tests/test_fx_railway.py -q
```

Expected: PASS, 12 tests.

- [ ] **Step 6: Run the Railway-side suites for regressions**

```bash
python3 -m pytest tests/test_gateway_hardening.py tests/test_proxy_bridge.py tests/test_session_registry_readonly.py -q
```

Expected: PASS, no new failures.

- [ ] **Step 7: Commit**

```bash
git add railway/features/fx/ railway/app.py tests/test_fx_railway.py
git commit -m "Relay /fx/* to the daemon, and pin its alphabet first

The prefix is not a security boundary — httpx resolves ../ at the far
end — so the path is constrained here, before the string can travel.
Registered above the two-segment catch-all that would otherwise read
/fx/<token> as a session named fx."
git push
```

---

### Task 10: Contracts and documentation

**Files:**
- Regenerate: `docs/openapi.yaml`, `API.md`
- Modify: `ARCHITECTURE.md`
- Modify: `backlog.md`

**Interfaces:**
- Consumes: the routers from Tasks 5, 6 and 9.
- Produces: nothing code depends on.

- [ ] **Step 1: Regenerate the API contract**

```bash
cd /Users/victorrentea/workspace/training-assistant
python3 scripts/generate_apis_md.py --output API.md
```

- [ ] **Step 2: Run the contract test**

```bash
python3 -m pytest tests/openapi/test_contract.py -q
```

Expected: PASS. If it fails on a snapshot mismatch, regenerate the snapshot the way the test's failure message instructs — do not edit `API.md` by hand.

- [ ] **Step 3: Update ARCHITECTURE.md**

Add the new edges to the C4 and system-interaction diagrams:

- daemon → `http://127.0.0.1:55123` (Victor Addons) → `:55124` (Victor Effects): a second, HTTP-shaped edge to the Mac apps, alongside the existing `ws://127.0.0.1:8765` bridge. Used for the soundboard catalog and tile presses.
- Railway `/fx/*` → daemon `/api/participant/fx/*`: a second public entry point beside the participant proxy, unauthenticated by design and independent of whether a session is active.

- [ ] **Step 4: Record the feature in the backlog**

Append to `backlog.md`:

```markdown
- **Secret FX link** (2026-09-16) — the host copies a secret URL from the
  footer 🎛️ popover and hands it to two or three people in the room; opening it
  gives them one button that presses a soundboard tile on the Mac (default #69,
  the wazzup ghost). Two brakes: a master switch that is off at the start of
  every session, and a server-side cooldown. Spans three repos — `/press/<n>` in
  victor-effects, one proxy prefix in victor-macos-addons, and `daemon/fx/` +
  `railway/features/fx/` here.
```

- [ ] **Step 5: Commit**

```bash
git add API.md docs/openapi.yaml ARCHITECTURE.md backlog.md
git commit -m "Record the FX link in the contracts and the diagrams

The daemon now has a second way to reach the Mac apps and Railway has a
second public entry point; both belong on the maps."
git push
```

---

### Task 11: Full check, deploy, and prove it in production

**Files:** none — this task is verification.

**Interfaces:**
- Consumes: everything.
- Produces: the evidence the feature works.

- [ ] **Step 1: Run the full local check**

```bash
cd /Users/victorrentea/workspace/training-assistant
uv run --extra dev --extra daemon --extra telemetry bash tests/check-all.sh 2>&1 | tee logs/fx-check-all.log | tail -30
```

(On Apple Silicon prefix with `arch -arm64`. The `--extra telemetry` is required in a fresh venv or the run dies on an opentelemetry collection error.)

Expected: PASS. Investigate any failure before continuing; do not proceed on red.

- [ ] **Step 2: Rebuild and restart the two Mac apps**

**Confirm with the user that no live session is running.** Then:

```bash
cd /Users/victorrentea/workspace/victor-effects && swift build -c release
cd /Users/victorrentea/workspace/victor-macos-addons && ./build-app.sh
pkill -f "Victor Addons"; open "/Applications/Victor Addons.app"
```

Restart Victor Effects the same way its own repo documents — via `open`, **never** by running the binary inside the bundle, or macOS registers a second app by path and the permissions do not follow.

- [ ] **Step 3: Prove the new route end to end on the Mac**

```bash
curl -s localhost:55123/press/999; echo    # expect {"ok":false,...,"reason":"unknown-tile"}
curl -s localhost:55123/press/69;  echo    # expect ok:true — this MAKES NOISE and shows the ghost
```

Expected: the second call plays `69_scream_ghost.mp3` and draws the Ghostface corner. This is the proof that Tasks 1 and 2 landed in the running apps.

- [ ] **Step 4: Confirm the Railway deploy actually happened**

```bash
curl -s https://interact.victorrentea.ro/api/status | python3 -m json.tool
```

Expected: `git_sha` matches the pushed commit. `railway/**` changed in Task 9, so a real deploy is due — unlike the usual "No deployment needed" case. Wait for it; a stale Railway answers 404 on `/fx/*`.

- [ ] **Step 5: Prove the public link works**

```bash
TOKEN=$(curl -s localhost:1234/api/cur/host/fx/state | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -o /dev/null -w "page  %{http_code}\n" "https://interact.victorrentea.ro/fx/$TOKEN"
curl -s "https://interact.victorrentea.ro/fx/$TOKEN/info"; echo
curl -s -X POST "https://interact.victorrentea.ro/fx/$TOKEN/fire"; echo
curl -s -o /dev/null -w "bad token %{http_code} (expect 404)\n" "https://interact.victorrentea.ro/fx/wrongtoken12"
curl -s -o /dev/null -w "traversal %{http_code} (expect 404)\n" "https://interact.victorrentea.ro/fx/../api/status"
```

Expected: the page 200s; `info` names tile 69; the first `fire` returns `disabled` until the host arms the switch, then `{"fired":true,"reason":"ok"}` **and the ghost appears on the Mac**; a second immediate `fire` returns `cooling`; the bad token and the traversal attempt both 404.

- [ ] **Step 6: Show the user**

Open the public link on a phone, arm the switch from the host page, press the button, and screenshot both surfaces — the trigger page and the host footer badge mid-flash.

- [ ] **Step 7: Report**

Summarise for the user: the URL, which tile it is bound to, how to change it, how to disarm it, and the reminder that the link dies when the session resets.

---

## Self-Review

**Spec coverage** — every section of the spec maps to a task: victor-effects → 1; victor-macos-addons → 2; `effects_client` → 3; state → 4; participant endpoints + `FxFiredMsg` + the page file → 5; host endpoints → 6; `static/fx.html` → 7; host UI → 8; Railway relay → 9; docs/contracts → 10; testing and deployment order → 11. The spec's security requirements are each pinned by a test: `compare_digest` and the flat 404 (Task 5), integer-only presses (Tasks 3 and 5), the path alphabet (Task 9), both brakes (Tasks 5 and 6).

**Deviations from the spec, deliberate:**
- The spec left the `POST /test` cooldown behaviour to "neither consumes nor observes"; Task 6 pins that with three tests, including that it does not take the lever away from someone holding the link.
- The spec did not say what happens when a press fails. Task 5 decides: no cooldown starts, so a closed soundboard does not lock the button ten seconds per attempt.
- The spec's `fx_last_fired_at` was described as a single field; the plan splits it into a persisted wall-clock stamp and an ephemeral monotonic one, and Task 4 tests that the monotonic one is never persisted.
- `reset()` also clears `fx_token`, which the spec implied ("each workshop gets a fresh one") but did not state.

**Placeholder scan:** none. Every code step carries the actual code; every test step carries the actual assertions and the expected output.

**Type consistency:** `press_tile(n: int) -> bool`, `fetch_tiles() -> list[dict] | None`, `fetch_tile_image(rel) -> tuple[bytes, str] | None` and `is_up() -> bool` are defined in Task 3 and used with those exact signatures in Tasks 5 and 6. `tile_label`/`find_tile`/`cooldown_remaining` are defined once in Task 5 and reused in Task 6. `FxFireResponse` is returned by both `POST /{token}/fire` and `POST /test`. The `reason` vocabulary — `ok | disabled | cooling | effects-down | no-tile` — is identical in the models, the tests, and the page's branches. `FxFiredMsg(tile_n, label, at)` is defined in Task 5 and consumed by `flashFxBadge` in Task 8 under the same field names.

**Known risk:** Task 8's WS dispatch and initial-load steps say "where the other host messages are handled" rather than a line number, because `static/host.js` is 173 KB and the dispatch site will have moved. The implementer must locate `bell_rung` in the host WS handler and follow it.
