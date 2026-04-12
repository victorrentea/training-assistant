# Slides BDD Feature — Hermetic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all 10 scenarios in `tests/docker/features/slides.feature` pass in the hermetic Docker environment using UI-only interactions (no direct HTTP calls for user actions). Generate PlantUML sequence diagrams from OTel traces with Given steps rendered in gray and When/Then steps in black.

**Architecture:** Step definitions drive Playwright page objects exclusively. Page objects (`HostPage`, `ParticipantPage`) are expanded as needed for slides-specific actions. OTel spans carry a `bdd.phase` attribute ("given", "when", "then") set by the step definition framework. The PlantUML generator uses this attribute to choose arrow color.

**Tech Stack:** pytest-bdd, Playwright, existing page objects, OTel tracing, PlantUML generator

---

## Key Constraints

- **No direct HTTP calls in When/Then steps** — all user actions go through page objects (button clicks, form fills, locator assertions)
- **Direct API calls allowed only for:** fresh session creation, mock Drive control, slide cache priming, addons bridge mock setup
- **Page objects must be expanded** to cover slides-specific actions not yet implemented
- **Docker must be used for verification** — every task that touches step definitions or page objects must be verified by running the hermetic test in Docker before marking complete
- **Generated PlantUML must distinguish BDD phases** — Given arrows in gray (`[#gray]`), When/Then arrows in black (default)

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/pages/participant_page.py` | Modify | Add slides methods: open_slide, navigate_to_page, click_follow, get_active_slide, get_page_indicator, get_catalog_slugs, get_catalog_timestamps |
| `tests/pages/host_page.py` | Modify | Add slides methods: upload_slide (via UI), invalidate_slide (via UI), get_slides_tab |
| `tests/docker/step_defs/test_slides.py` | Rewrite | UI-only step definitions using page objects, BDD phase tracking for OTel |
| `tests/docker/step_defs/conftest.py` | Modify | Add shared Given steps for slides (host connected, participant joins), BDD phase OTel hook |
| `scripts/traces_to_puml.py` | Modify | Add `bdd.phase` attribute → gray/black arrow rendering |
| `tests/docker/test_sequence_extraction.py` | Modify | Add slides sequence extraction test |
| `daemon/telemetry/ws_propagation.py` | Modify | Propagate `bdd.phase` attribute through spans |

---

### Task 1: Expand ParticipantPage with slides methods

**Files:**
- Modify: `tests/pages/participant_page.py`

New methods needed:

- [ ] **Step 1: Add `open_slide(slug)` method**

Click the slide item in the catalog sidebar by slug, wait for overlay to open.

```python
def open_slide(self, slug: str) -> None:
    """Click a slide in the catalog to open it in the viewer."""
    self._page.locator(f'.slides-list-item[data-slug="{slug}"] .slides-list-open').click()
    expect(self._page.locator("#slides-overlay")).to_have_class(re.compile(r"open"), timeout=15000)
```

- [ ] **Step 2: Add `navigate_to_page(page_num)` method**

Click next-page button to reach target page.

```python
def navigate_to_page(self, target_page: int) -> None:
    """Navigate to a specific page in the currently open slide."""
    for _ in range(target_page - 1):
        self._page.locator("#slides-page-next").click()
        self._page.wait_for_timeout(300)
```

- [ ] **Step 3: Add `click_follow()` method**

```python
def click_follow(self) -> None:
    self._page.locator("#slides-follow-btn").click()
```

- [ ] **Step 4: Add `get_page_indicator()` method**

```python
def get_page_indicator(self) -> str:
    """Return current page indicator text, e.g. 'Page 3/5'."""
    return self._page.locator("#slides-page-inline").inner_text()
```

- [ ] **Step 5: Add `get_catalog_slugs()` method**

```python
def get_catalog_slugs(self) -> list[str]:
    """Return list of slide slugs visible in the catalog."""
    items = self._page.locator(".slides-list-item").all()
    return [item.get_attribute("data-slug") for item in items if item.get_attribute("data-slug")]
```

- [ ] **Step 6: Add `get_catalog_timestamp(slug)` method**

```python
def get_catalog_timestamp(self, slug: str) -> str:
    """Return the last-modified timestamp label for a catalog item."""
    item = self._page.locator(f'.slides-list-item[data-slug="{slug}"] .slides-list-updated')
    return item.inner_text() if item.count() > 0 else ""
```

- [ ] **Step 7: Add `is_overlay_open()` method**

```python
def is_overlay_open(self) -> bool:
    return "open" in (self._page.locator("#slides-overlay").get_attribute("class") or "")
```

- [ ] **Step 8: Add `screenshot_viewer()` method for visual assertions**

```python
def screenshot_viewer(self) -> bytes:
    """Take a screenshot of the slides viewer area."""
    viewer = self._page.locator("#slides-pdf-viewer, #slides-native-frame")
    expect(viewer).to_be_visible(timeout=15000)
    self._page.wait_for_timeout(1000)
    return viewer.screenshot()
```

- [ ] **Step 9: Commit**

```bash
git add tests/pages/participant_page.py
git commit -m "feat(pages): expand ParticipantPage with slides methods"
```

---

### Task 2: Expand HostPage with slides methods

**Files:**
- Modify: `tests/pages/host_page.py`

- [ ] **Step 1: Add `open_slides_tab()` method**

```python
def open_slides_tab(self) -> None:
    """Switch to slides tab (the default 'none' activity shows slides)."""
    self._page.evaluate("async () => { await switchTab('none'); }")
```

- [ ] **Step 2: Add `upload_slide(slug, pdf_bytes)` method**

Upload via the host UI file input (not REST API).

```python
def upload_slide(self, slug: str, pdf_bytes: bytes) -> None:
    """Upload a slide PDF via the host UI."""
    # The host page has a file input for slide upload
    # Use Playwright's set_input_files with a buffer
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".pdf", prefix=slug + "-", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = f.name
    try:
        file_input = self._page.locator('input[type="file"][accept*="pdf"]')
        file_input.set_input_files(tmp_path)
        self._page.wait_for_timeout(2000)  # wait for upload + WS broadcast
    finally:
        os.unlink(tmp_path)
```

- [ ] **Step 3: Commit**

```bash
git add tests/pages/host_page.py
git commit -m "feat(pages): expand HostPage with slides upload method"
```

---

### Task 3: Rewrite step definitions — UI only

**Files:**
- Rewrite: `tests/docker/step_defs/test_slides.py`

This is the core task. Every When/Then step must use page object methods. Given steps may use API calls only for non-UI setup (session creation, mock drive, addons bridge).

- [ ] **Step 1: Rewrite all When steps to use page objects**

Replace all `_api()` calls in When steps with page object methods:
- `When Alice opens slide "X"` → `_pax("Alice").open_slide("X")`
- `When Alice navigates to page N` → `_pax("Alice").navigate_to_page(N)`
- `When Alice clicks the Follow button` → `_pax("Alice").click_follow()`
- `When Bob joins as a participant` → create browser context, join via page object
- `When the host updates the slide "X"` → host page object uploads new version via UI
- `When the addons bridge reports...` → mock WS server sends slide event (this is mock control, not UI)

- [ ] **Step 2: Rewrite all Then steps to use page object assertions**

Replace all API-based assertions with page locator assertions:
- `Then Alice sees the slides overlay` → `expect(pax.locator("#slides-overlay")).to_be_visible()`
- `Then the active slide is "X"` → check `.slides-list-item.active[data-slug="X"]`
- `Then Alice sees page N of "X"` → check page indicator text
- `Then the slide content is visually rendered` → screenshot + pixel variety check
- `Then the slides catalog contains "X" with a last modified timestamp` → check `.slides-list-updated` text
- `Then Google Drive was called N time(s)` → mock drive stats (this is infra assertion, OK as API)

- [ ] **Step 3: Add BDD phase tracking via OTel span attributes**

Add a pytest-bdd hook that sets `bdd.phase` attribute on current OTel span:

```python
@pytest.hookimpl
def pytest_bdd_before_step(request, feature, scenario, step, step_func):
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("bdd.phase", step.keyword.lower().strip())
    except ImportError:
        pass
```

- [ ] **Step 4: Run in Docker and iterate until all 10 scenarios pass**

Run: `bash tests/docker/run-hermetic.sh -k test_slides -m "not nightly" -s`

Fix failures one at a time. Common issues:
- Timing (add waits/timeouts)
- Locator selectors not matching (check actual DOM)
- Mock drive not ready (add polling)

- [ ] **Step 5: Commit**

```bash
git add tests/docker/step_defs/test_slides.py
git commit -m "feat(slides): UI-only BDD step definitions for all 10 scenarios"
```

---

### Task 4: PlantUML generator — gray/black arrows from BDD phase

**Files:**
- Modify: `scripts/traces_to_puml.py`
- Test: `tests/daemon/test_traces_to_puml.py`

- [ ] **Step 1: Add test for BDD phase coloring**

```python
def test_given_phase_renders_gray():
    """Spans with bdd.phase=given produce gray arrows."""
    # ... create spans with bdd.phase attribute ...
    # Assert arrow uses [#gray] PlantUML color syntax
```

- [ ] **Step 2: Update `_extract_edges` to carry BDD phase**

Change edge tuple from `(from, to, label, start_time)` to `(from, to, label, start_time, phase)` where phase is `"given"`, `"when"`, `"then"`, or `""`.

- [ ] **Step 3: Update PlantUML rendering to use color**

```python
for f, t, label, _, phase in edges:
    arrow = "-->" if label.startswith("broadcast ") or label.startswith("notify_host ") else "->"
    color = "[#gray]" if phase == "given" else ""
    lines.append(f'"{f}" {color}{arrow} "{t}": {label}')
```

PlantUML syntax: `"A" -[#gray]-> "B": label` renders a gray arrow.

- [ ] **Step 4: Run unit tests**

Run: `PYTHONPATH=. arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_traces_to_puml.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/traces_to_puml.py tests/daemon/test_traces_to_puml.py
git commit -m "feat(telemetry): render BDD Given phase as gray arrows in PlantUML"
```

---

### Task 5: Slides sequence extraction hermetic test

**Files:**
- Modify: `tests/docker/test_sequence_extraction.py`

- [ ] **Step 1: Add slides sequence extraction test**

Add a test that runs the full slides feature flow (follow mode scenario is the most interesting), collects traces, and generates PlantUML to `docs/sequences/generated/06-slides.puml`.

- [ ] **Step 2: Run in Docker**

Run: `bash tests/docker/run-hermetic.sh -k test_slides_sequence_diagram_extraction -m nightly -s`

- [ ] **Step 3: Commit generated diagram**

```bash
git add docs/sequences/generated/06-slides.puml tests/docker/test_sequence_extraction.py
git commit -m "docs: generated slides sequence diagram from hermetic traces"
```

---

### Task 6: Verify all scenarios pass and push

- [ ] **Step 1: Run full slides feature in Docker**

Run: `bash tests/docker/run-hermetic.sh -k test_slides -s`

All 10 scenarios must pass.

- [ ] **Step 2: Run full hermetic suite to check for regressions**

Run: `bash tests/docker/run-hermetic.sh`

- [ ] **Step 3: Push to master**

```bash
git push origin master
```

---

## Execution Notes

**Task dependencies:** Task 1-2 (page objects) must complete before Task 3 (step definitions). Task 4 (generator) is independent. Task 5 depends on Tasks 3+4. Task 6 depends on all.

**Docker iteration:** Task 3 will require multiple Docker runs to debug timing and selector issues. Expect 3-5 iterations.

**Page object expansion:** The exact methods needed may evolve during Task 3 as we discover what the actual DOM structure requires. Update page objects as needed.

**Mock addons bridge:** The existing mock from `test_follow_me.py` should be reused. It needs to support sending multiple slide events (for the auto-advance scenario).
