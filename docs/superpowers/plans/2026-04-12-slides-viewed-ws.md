# Slides Viewed WebSocket Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace file-based slide duration tracking between victor-macos-addons and the training-assistant daemon with a WebSocket message (`slides_viewed`) sent every 60 seconds, persisted in `PersistedSessionState.slides_viewed`.

**Architecture:** The addons PowerPointMonitor already tracks per-slide durations in memory (`slideDurations`) and writes them to a `YYYY-MM-DD-slides.txt` file. We add a 60-second timer that computes **delta** durations (seconds since last send), fires a new `onSlidesViewed` callback, which flows through the existing LocalWebSocketServer (port 8765) to the daemon's `AddonBridgeClient`. The daemon merges incoming deltas into `misc_state.slides_viewed` (a list of `ViewedSlide` objects), persists them in session snapshots, and serves them via the existing `slides_log` host state fields — replacing the file-reading `activity_reader.read_slides_log()` call.

**Tech Stack:** Swift (macOS app), Python (FastAPI, Pydantic), WebSocket (NWProtocol / websockets)

**Important:** Two repos are involved:
- **Addons:** `/Users/victorrentea/workspace/victor-macos-addons` (Swift)
- **Daemon:** `/Users/victorrentea/workspace/training-assistant` (Python)

---

## File Map

### Addons (victor-macos-addons)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `Sources/VictorAddons/PowerPointMonitor.swift` | Add 60s timer, cross-deck accumulation, delta computation, `onSlidesViewed` callback |
| Modify | `Sources/VictorAddons/LocalWebSocketServer.swift` | Add `pushSlidesViewed()` broadcast method |
| Modify | `Sources/VictorAddons/AppDelegate.swift:196-201` | Wire `onSlidesViewed` callback to WS server |

### Daemon (training-assistant)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `daemon/persisted_models.py:86` | Add `ViewedSlide` model and `slides_viewed` field to `PersistedSessionState` |
| Modify | `daemon/misc/state.py:6-22` | Add `slides_viewed: list[dict]` to `MiscState`, handle in `sync_from_restore`, `reset_for_new_session`, `snapshot` |
| Modify | `daemon/addon_bridge_client.py:25-70` | Add `_slides_viewed_queue`, `drain_slides_viewed()`, handle `type == "slides_viewed"` |
| Modify | `daemon/__main__.py:258-260` | Include `slides_viewed` in runtime snapshot |
| Modify | `daemon/__main__.py:1037` | Add main-loop section to drain and merge `slides_viewed` events |
| Modify | `daemon/host_state_router.py:348-366` | Replace `read_slides_log()` file read with `misc_state.slides_viewed` |
| Create | `tests/unit/test_slides_viewed_merge.py` | Unit tests for merge logic |
| Modify | `tests/unit/test_activity_reader.py` | Keep existing tests (activity_reader not deleted yet) |
| Modify | `tests/daemon/test_host_state_router.py` | Update test for new slides_log source |

---

## Task 1: Add `ViewedSlide` model and `slides_viewed` field to persisted state

**Files:**
- Modify: `daemon/persisted_models.py:86-142`

- [ ] **Step 1: Add ViewedSlide model**

Add above `PersistedSessionState` (around line 86):

```python
class ViewedSlide(PersistedModel):
    """Single slide viewing record: cumulative seconds on one (file, page) pair."""
    file_name: str = Field(description="PowerPoint file name, e.g. 'AI Coding.pptx'")
    page: int = Field(description="1-based slide number")
    seconds: int = Field(default=0, description="Cumulative seconds viewed")
```

- [ ] **Step 2: Add slides_viewed field to PersistedSessionState**

After the `slides_current` field (line 142), add:

```python
    slides_viewed: list[ViewedSlide] = Field(default_factory=list, description="Accumulated per-slide viewing durations from addons")
```

- [ ] **Step 3: Verify model loads**

Run: `python3 -c "from daemon.persisted_models import PersistedSessionState, ViewedSlide; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add daemon/persisted_models.py
git commit -m "feat(slides): add ViewedSlide model and slides_viewed to PersistedSessionState"
```

---

## Task 2: Add `slides_viewed` to MiscState (in-memory runtime state)

**Files:**
- Modify: `daemon/misc/state.py`

- [ ] **Step 1: Add slides_viewed field to MiscState.__init__**

After `self.slides_current` (line 22), add:

```python
        self.slides_viewed: list[dict] = []  # [{file_name, page, seconds}]
```

- [ ] **Step 2: Handle slides_viewed in sync_from_restore**

Inside `sync_from_restore()`, after the `slides_current` block (line 59), add:

```python
            if "slides_viewed" in data:
                self.slides_viewed = list(data.get("slides_viewed") or [])
```

- [ ] **Step 3: Clear slides_viewed in reset_for_new_session**

After `self.slides_current = None` (line 150), add:

```python
            self.slides_viewed = []
```

- [ ] **Step 4: Include slides_viewed in snapshot**

In the `snapshot()` method (line 133), add to the returned dict:

```python
            "slides_viewed": [dict(sv) for sv in self.slides_viewed],
```

- [ ] **Step 5: Verify import**

Run: `python3 -c "from daemon.misc.state import misc_state; print(misc_state.slides_viewed)"`
Expected: `[]`

- [ ] **Step 6: Commit**

```bash
git add daemon/misc/state.py
git commit -m "feat(slides): add slides_viewed to MiscState with snapshot/restore/reset"
```

---

## Task 3: Add slides_viewed to daemon runtime snapshot

**Files:**
- Modify: `daemon/__main__.py:258-260`

- [ ] **Step 1: Include slides_viewed in _build_runtime_session_snapshot**

In `_build_runtime_session_snapshot()`, after `"slides_current": misc_state.slides_current,` (line 260), add:

```python
        "slides_viewed": [dict(sv) for sv in misc_state.slides_viewed],
```

- [ ] **Step 2: Commit**

```bash
git add daemon/__main__.py
git commit -m "feat(slides): include slides_viewed in session snapshot"
```

---

## Task 4: Handle `slides_viewed` messages in AddonBridgeClient

**Files:**
- Modify: `daemon/addon_bridge_client.py`

- [ ] **Step 1: Add slides_viewed queue**

In `__init__` (around line 31), after `self._slide_queue`, add:

```python
        self._slides_viewed_queue: queue.Queue = queue.Queue()
```

- [ ] **Step 2: Add drain_slides_viewed method**

After the `drain_slides()` method (line 70), add:

```python
    def drain_slides_viewed(self) -> list[list[dict]]:
        """Return all pending slides_viewed batches. Call from the main thread each loop."""
        batches: list[list[dict]] = []
        while True:
            try:
                batches.append(self._slides_viewed_queue.get_nowait())
            except queue.Empty:
                break
        return batches
```

- [ ] **Step 3: Handle slides_viewed message type**

In `_connect_and_listen()`, after the `if data.get("type") == "slide":` block (line 147), add:

```python
                elif data.get("type") == "slides_viewed":
                    slides = data.get("slides", [])
                    if slides:
                        self._slides_viewed_queue.put(slides)
```

- [ ] **Step 4: Update module docstring**

Update the docstring at the top (lines 1-11) to document the new message type:

```
  Addons → Daemon: {"type": "slides_viewed", "slides": [{"fileName": "<name>", "page": <n>, "seconds": <n>}, ...]}
              — periodic (60s) delta of per-slide viewing durations
```

- [ ] **Step 5: Commit**

```bash
git add daemon/addon_bridge_client.py
git commit -m "feat(slides): handle slides_viewed WS message in AddonBridgeClient"
```

---

## Task 5: Write merge logic + unit tests

**Files:**
- Create: `tests/unit/test_slides_viewed_merge.py`

The merge function will live in the main loop inline (it's simple enough), but we test the logic here via a helper we extract for testability.

- [ ] **Step 1: Create merge helper module**

Create `daemon/slides/merge_viewed.py`:

```python
"""Merge incoming slides_viewed deltas into the accumulated list."""


def merge_slides_viewed(
    existing: list[dict],
    incoming: list[dict],
) -> None:
    """Merge incoming delta entries into existing list, in place.

    For each incoming entry:
      - If (file_name, page) exists in existing, add seconds to it.
      - Otherwise, append a new entry (preserving insertion order).

    Args:
        existing: The current slides_viewed list (mutated in place).
        incoming: Delta entries with keys: fileName, page, seconds.
    """
    index: dict[tuple[str, int], int] = {}
    for i, sv in enumerate(existing):
        key = (sv["file_name"], sv["page"])
        index[key] = i

    for entry in incoming:
        file_name = entry.get("fileName", "")
        page = entry.get("page", 0)
        seconds = entry.get("seconds", 0)
        if not file_name or not page or seconds <= 0:
            continue
        key = (file_name, page)
        if key in index:
            existing[index[key]]["seconds"] += seconds
        else:
            index[key] = len(existing)
            existing.append({"file_name": file_name, "page": page, "seconds": seconds})
```

- [ ] **Step 2: Write failing tests**

Create `tests/unit/test_slides_viewed_merge.py`:

```python
"""Unit tests for daemon.slides.merge_viewed."""

from daemon.slides.merge_viewed import merge_slides_viewed


def test_merge_into_empty():
    existing = []
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 3, "seconds": 45},
        {"fileName": "AI.pptx", "page": 4, "seconds": 12},
    ])
    assert len(existing) == 2
    assert existing[0] == {"file_name": "AI.pptx", "page": 3, "seconds": 45}
    assert existing[1] == {"file_name": "AI.pptx", "page": 4, "seconds": 12}


def test_merge_adds_seconds_to_existing():
    existing = [{"file_name": "AI.pptx", "page": 3, "seconds": 100}]
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 3, "seconds": 20},
    ])
    assert len(existing) == 1
    assert existing[0]["seconds"] == 120


def test_merge_preserves_order():
    existing = [
        {"file_name": "AI.pptx", "page": 1, "seconds": 10},
        {"file_name": "AI.pptx", "page": 2, "seconds": 20},
    ]
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 2, "seconds": 5},
        {"fileName": "AI.pptx", "page": 3, "seconds": 30},
    ])
    assert len(existing) == 3
    assert existing[0] == {"file_name": "AI.pptx", "page": 1, "seconds": 10}
    assert existing[1] == {"file_name": "AI.pptx", "page": 2, "seconds": 25}
    assert existing[2] == {"file_name": "AI.pptx", "page": 3, "seconds": 30}


def test_merge_skips_zero_seconds():
    existing = []
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 1, "seconds": 0},
    ])
    assert existing == []


def test_merge_skips_missing_fields():
    existing = []
    merge_slides_viewed(existing, [
        {"page": 1, "seconds": 10},
        {"fileName": "AI.pptx", "seconds": 10},
    ])
    assert existing == []


def test_merge_cross_deck():
    existing = [{"file_name": "AI.pptx", "page": 1, "seconds": 10}]
    merge_slides_viewed(existing, [
        {"fileName": "Java.pptx", "page": 1, "seconds": 30},
    ])
    assert len(existing) == 2
    assert existing[1] == {"file_name": "Java.pptx", "page": 1, "seconds": 30}
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python3 -m pytest tests/unit/test_slides_viewed_merge.py -v`
Expected: All 6 tests PASS

- [ ] **Step 4: Commit**

```bash
git add daemon/slides/merge_viewed.py tests/unit/test_slides_viewed_merge.py
git commit -m "feat(slides): add merge_slides_viewed helper with unit tests"
```

---

## Task 6: Wire merge logic into daemon main loop

**Files:**
- Modify: `daemon/__main__.py:1037`

- [ ] **Step 1: Add merge processing after slide events**

After the existing slide event processing block (around line 1037, right before `# ── Push overlay_connected state change to host ──`), add:

```python
            # ── Process slides_viewed deltas from addon bridge ──
            for _sv_batch in _bridge.drain_slides_viewed():
                from daemon.slides.merge_viewed import merge_slides_viewed
                merge_slides_viewed(misc_state.slides_viewed, _sv_batch)
```

- [ ] **Step 2: Verify daemon starts**

Run: `python3 -m daemon --help` (or any quick smoke check that imports succeed)
Expected: No import errors

- [ ] **Step 3: Commit**

```bash
git add daemon/__main__.py
git commit -m "feat(slides): merge slides_viewed deltas in daemon main loop"
```

---

## Task 7: Replace file-based slides_log with in-memory slides_viewed

**Files:**
- Modify: `daemon/host_state_router.py:348-366`

- [ ] **Step 1: Rewrite _build_slides_log_fields**

Replace the current `_build_slides_log_fields()` function (lines 348-366) with:

```python
def _build_slides_log_fields() -> dict:
    """Compute slides_log, slides_log_deep_count, slides_log_topic from in-memory slides_viewed."""

    slides_log = [
        {"file": sv["file_name"], "slide": sv["page"], "seconds_spent": sv["seconds"]}
        for sv in misc_state.slides_viewed
    ]
    deep_count = len({(e["file"], e["slide"]) for e in slides_log})
    if misc_state.slides_current and misc_state.slides_current.get("presentation_name"):
        topic = misc_state.slides_current["presentation_name"]
    elif slides_log:
        topic = max(slides_log, key=lambda e: e["seconds_spent"])["file"]
    else:
        topic = None
    return {
        "slides_log": slides_log,
        "slides_log_deep_count": deep_count,
        "slides_log_topic": topic,
    }
```

- [ ] **Step 2: Remove the read_slides_log import**

Remove line 22: `from daemon.slides.activity_reader import read_slides_log`

Also remove the `_session_date_from_entry` helper (lines 336-345) if it is no longer used by any other function in the file. Check if `_build_git_repos_fields` (line 374) still uses it — if yes, keep it.

- [ ] **Step 3: Remove TRANSCRIPTION_FOLDER usage from _build_slides_log_fields**

The `folder` variable and `os.environ.get("TRANSCRIPTION_FOLDER", ...)` in the old function body are no longer needed for slides (but check that `_build_git_repos_fields` still has its own copy — it does, at line 376).

- [ ] **Step 4: Run daemon unit tests**

Run: `python3 -m pytest tests/daemon/test_host_state_router.py -v --confcutdir=tests/daemon`
Expected: Tests pass (may need updating — see next step)

- [ ] **Step 5: Update host_state_router test if needed**

The existing test `test_build_slides_log_fields_uses_active_session_entry` in `tests/daemon/test_host_state_router.py` mocks `read_slides_log`. Update it to populate `misc_state.slides_viewed` instead:

```python
def test_build_slides_log_fields_reads_from_misc_state(monkeypatch):
    from daemon.misc.state import misc_state
    misc_state.slides_viewed = [
        {"file_name": "AI.pptx", "page": 3, "seconds": 120},
        {"file_name": "AI.pptx", "page": 4, "seconds": 30},
    ]
    misc_state.slides_current = None
    from daemon.host_state_router import _build_slides_log_fields
    result = _build_slides_log_fields()
    assert result["slides_log_deep_count"] == 2
    assert len(result["slides_log"]) == 2
    assert result["slides_log"][0]["file"] == "AI.pptx"
    assert result["slides_log"][0]["seconds_spent"] == 120
    # Cleanup
    misc_state.slides_viewed = []
```

- [ ] **Step 6: Run all daemon tests**

Run: `python3 -m pytest tests/daemon/ tests/unit/ -v --confcutdir=tests/daemon`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add daemon/host_state_router.py tests/daemon/test_host_state_router.py
git commit -m "feat(slides): replace file-based slides_log with in-memory slides_viewed"
```

---

## Task 8: Add cross-deck accumulation + 60s delta timer to PowerPointMonitor (addons)

**Files:**
- Modify: `Sources/VictorAddons/PowerPointMonitor.swift`

- [ ] **Step 1: Add new callback and state variables**

After the `onSlideChange` callback (line 47), add:

```swift
    var onSlidesViewed: (([[String: Any]]) -> Void)?
```

Add new state variables after `lineStartTime` (line 59):

```swift
    private var allDurations: [String: [Int: TimeInterval]] = [:]  // deck → slide → cumulative secs
    private var lastSentDurations: [String: [Int: TimeInterval]] = [:]  // deck → slide → secs already sent
    private var sendTimer: Timer?
```

- [ ] **Step 2: Accumulate into allDurations on every tick**

In `tick()`, after the time accumulation block (line 110, `slideDurations[currentSlide]! += elapsed`), add accumulation into the cross-deck tracker:

```swift
            // Also accumulate into cross-deck tracker
            if var deckMap = allDurations[currentDeck!] {
                deckMap[currentSlide, default: 0] += elapsed
                allDurations[currentDeck!] = deckMap
            } else {
                allDurations[currentDeck!] = [currentSlide: elapsed]
            }
```

- [ ] **Step 3: Add 60s send timer in start()**

In `start()`, after the existing 3s timer setup (line 67-70), add:

```swift
            self?.sendTimer = Timer.scheduledTimer(withTimeInterval: 60.0, repeats: true) { [weak self] _ in
                DispatchQueue.global(qos: .utility).async { self?.sendDelta() }
            }
```

- [ ] **Step 4: Invalidate sendTimer in stop()**

In `stop()` (line 73-76), add:

```swift
        sendTimer?.invalidate()
        sendTimer = nil
```

- [ ] **Step 5: Add sendDelta() method**

Add a new private method:

```swift
    private func sendDelta() {
        var entries: [[String: Any]] = []
        for (deck, slides) in allDurations {
            let sentSlides = lastSentDurations[deck] ?? [:]
            for (slideNum, totalSecs) in slides {
                let alreadySent = sentSlides[slideNum] ?? 0
                let delta = totalSecs - alreadySent
                if delta >= 0.5 {
                    entries.append([
                        "fileName": deck,
                        "page": slideNum,
                        "seconds": Int(delta.rounded()),
                    ])
                }
            }
        }
        if !entries.isEmpty {
            onSlidesViewed?(entries)
            // Update lastSent to current
            lastSentDurations = allDurations.mapValues { slideMap in
                slideMap.mapValues { $0 }
            }
        }
    }
```

- [ ] **Step 6: Build and verify**

Run: `swift build` in the victor-macos-addons directory.
Expected: Build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
cd ~/workspace/victor-macos-addons
git add Sources/VictorAddons/PowerPointMonitor.swift
git commit -m "feat(slides): add 60s slides_viewed delta timer with cross-deck accumulation"
```

---

## Task 9: Add pushSlidesViewed to LocalWebSocketServer (addons)

**Files:**
- Modify: `Sources/VictorAddons/LocalWebSocketServer.swift`

- [ ] **Step 1: Add pushSlidesViewed method**

After the `pushSlide()` method (line 63), add:

```swift
    func pushSlidesViewed(_ slides: [[String: Any]]) {
        let msg: [String: Any] = ["type": "slides_viewed", "slides": slides]
        guard let data = try? JSONSerialization.data(withJSONObject: msg),
              let text = String(data: data, encoding: .utf8) else { return }
        queue.async { [weak self] in
            self?.broadcast(text)
        }
    }
```

- [ ] **Step 2: Build and verify**

Run: `swift build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add Sources/VictorAddons/LocalWebSocketServer.swift
git commit -m "feat(slides): add pushSlidesViewed broadcast method"
```

---

## Task 10: Wire onSlidesViewed in AppDelegate (addons)

**Files:**
- Modify: `Sources/VictorAddons/AppDelegate.swift:196-201`

- [ ] **Step 1: Wire callback**

After the existing `pptMonitor.onSlideChange` wiring (line 197-199), add:

```swift
        pptMonitor.onSlidesViewed = { [weak self] slides in
            self?.wsServer?.pushSlidesViewed(slides)
        }
```

- [ ] **Step 2: Build and verify**

Run: `swift build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add Sources/VictorAddons/AppDelegate.swift
git commit -m "feat(slides): wire onSlidesViewed callback to WS server push"
```

---

## Task 11: Run full test suites on both repos

**Files:** None (verification only)

- [ ] **Step 1: Run daemon tests**

Run: `cd ~/workspace/training-assistant && bash tests/check-all.sh`
Expected: All tests pass.

- [ ] **Step 2: Run addons build**

Run: `cd ~/workspace/victor-macos-addons && swift build`
Expected: Build succeeds.

- [ ] **Step 3: Manual smoke test (if daemon + addons running)**

1. Start daemon and addons
2. Open a PowerPoint presentation and navigate slides
3. Wait 60 seconds
4. Check daemon logs for `slides_viewed` processing (or call `GET /{session_id}/host/state` and check `slides_log`)

---

## Notes

### What is NOT changed (intentionally)

- **`activity_reader.py`**: Kept as-is. It can be deprecated later once the WS flow is proven stable. No code references it after Task 7 except its own unit tests.
- **`PowerPointMonitor.writeFile()`**: The text file write is kept for now as a local backup/log. Can be removed in a follow-up.
- **`SlidesLogEntry.timestamp` field**: The host response model has a `timestamp` field, but the current `_build_slides_log_fields` never populates it. The new implementation doesn't add it either — this was already a gap. Can be addressed separately.
- **Session filtering (paused_intervals)**: The old `activity_reader` filtered by session start time and pause intervals. The new flow doesn't need this because the daemon only receives deltas while running during an active session. If the addons sends data during a pause, the daemon is already paused and won't process the main loop. If finer-grained filtering is needed later, it can be added to the merge step.

### Message protocol

```
Addons → Daemon (via port 8765):
{
  "type": "slides_viewed",
  "slides": [
    {"fileName": "AI Coding.pptx", "page": 3, "seconds": 45},
    {"fileName": "AI Coding.pptx", "page": 4, "seconds": 12}
  ]
}
```

- Sent every 60 seconds as a **delta** (only new seconds since last send)
- `fileName` matches the PowerPoint file name (e.g. `"AI Coding.pptx"`)
- `page` is 1-based slide number
- `seconds` is an integer (rounded from TimeInterval)
- Only entries with delta >= 0.5s are included
