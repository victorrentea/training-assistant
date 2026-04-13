# OTel Sequence Diagram Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument all 5 actors with OpenTelemetry, collect traces during hermetic tests, and extract PlantUML sequence diagrams from them. Manual comparison against existing hand-written diagrams (automated comparison deferred).

**Architecture:** OTel auto-instrumentation on Python backends (FastAPI HTTP), manual WS trace propagation at 5 choke points, OTel JS SDK in browsers via CDN. Spans written to a shared JSONL file via custom FileSpanExporter. A post-test script reconstructs sequence diagrams from traces, applying generic rules to collapse Railway proxy/broadcast intermediaries.

**Tech Stack:** opentelemetry-python (API + SDK + auto-instrumentation), @opentelemetry/sdk-trace-web (browser CDN), PlantUML, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `daemon/telemetry/__init__.py` | Create | OTel setup: configure FileSpanExporter, propagation helpers |
| `daemon/telemetry/file_exporter.py` | Create | FileSpanExporter that writes JSONL to disk |
| `daemon/telemetry/ws_propagation.py` | Create | Dict-based inject/extract helpers for WS messages |
| `daemon/ws_publish.py` | Modify | Inject `_traceparent` in broadcast() and notify_host() |
| `daemon/proxy_handler.py` | Modify | Extract `_traceparent` from proxy_request, create child span |
| `daemon/addon_bridge_client.py` | Modify | Inject/extract `_traceparent` on send/receive |
| `railway/features/telemetry/__init__.py` | Create | Empty package init |
| `railway/features/telemetry/router.py` | Create | POST /api/telemetry/spans endpoint |
| `railway/features/ws/proxy_bridge.py` | Modify | Inject `traceparent` into proxy_request dict |
| `railway/features/ws/router.py` | Modify | Pass through `_traceparent` in broadcast fan-out (already works — no change needed) |
| `railway/app.py` | Modify | Register telemetry router when OTel enabled |
| `static/otel-init.js` | Create | Browser OTel SDK init, fetch instrumentation, WS context |
| `static/participant.html` | Modify | Add CDN script tags + otel-init.js |
| `static/host.html` | Modify | Add CDN script tags + otel-init.js |
| `scripts/traces_to_puml.py` | Create | Trace JSONL → PlantUML generator with collapse rules |
| `tests/daemon/test_traces_to_puml.py` | Create | Unit tests for the generator |
| `tests/docker/test_sequence_extraction.py` | Create | Hermetic test that generates diagrams from traces |
| `tests/docker/start_hermetic.sh` | Modify | Add OTEL env vars, wrap startup with opentelemetry-instrument |
| `tests/docker/Dockerfile.hermetic` | Modify | Install OTel Python packages |
| `pyproject.toml` | Modify | Add OTel dependencies to optional-dependencies |

---

### Task 1: Python OTel dependencies and FileSpanExporter

**Files:**
- Modify: `pyproject.toml` (optional-dependencies section)
- Create: `daemon/telemetry/__init__.py`
- Create: `daemon/telemetry/file_exporter.py`
- Test: `tests/daemon/test_file_exporter.py`

- [ ] **Step 1: Write the failing test for FileSpanExporter**

```python
# tests/daemon/test_file_exporter.py
import json
import tempfile
from pathlib import Path


def test_file_exporter_writes_jsonl():
    from daemon.telemetry.file_exporter import FileSpanExporter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    exporter = FileSpanExporter(path)

    # Create a minimal mock span with to_json()
    class FakeSpan:
        def to_json(self):
            return json.dumps({"name": "test-span", "trace_id": "abc123"})

    from opentelemetry.sdk.trace.export import SpanExportResult

    result = exporter.export([FakeSpan(), FakeSpan()])
    assert result == SpanExportResult.SUCCESS

    lines = Path(path).read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "test-span"


def test_file_exporter_appends_not_overwrites():
    from daemon.telemetry.file_exporter import FileSpanExporter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    exporter = FileSpanExporter(path)

    class FakeSpan:
        def __init__(self, name):
            self._name = name
        def to_json(self):
            return json.dumps({"name": self._name})

    exporter.export([FakeSpan("first")])
    exporter.export([FakeSpan("second")])

    lines = Path(path).read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "first"
    assert json.loads(lines[1])["name"] == "second"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_file_exporter.py -v --confcutdir=tests/daemon`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.telemetry'`

- [ ] **Step 3: Add OTel dependencies to pyproject.toml**

In `pyproject.toml`, add a new optional dependency group after the existing `daemon` group:

```toml
telemetry = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
    "opentelemetry-instrumentation-fastapi>=0.41b0",
    "opentelemetry-instrumentation-urllib>=0.41b0",
    "opentelemetry-distro>=0.41b0",
]
```

- [ ] **Step 4: Implement FileSpanExporter**

```python
# daemon/telemetry/__init__.py
"""OpenTelemetry setup for daemon and Railway."""
```

```python
# daemon/telemetry/file_exporter.py
"""FileSpanExporter — writes spans as JSONL to a file on disk."""
import threading

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class FileSpanExporter(SpanExporter):
    """Append one JSON line per span to a file. Thread-safe."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()

    def export(self, spans):
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                for span in spans:
                    f.write(span.to_json() + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=None):
        return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `arch -arm64 uv run --extra dev --extra daemon --extra telemetry python -m pytest tests/daemon/test_file_exporter.py -v --confcutdir=tests/daemon`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml daemon/telemetry/__init__.py daemon/telemetry/file_exporter.py tests/daemon/test_file_exporter.py
git commit -m "feat(telemetry): add OTel deps and FileSpanExporter"
```

---

### Task 2: WS trace propagation helpers

**Files:**
- Create: `daemon/telemetry/ws_propagation.py`
- Test: `tests/daemon/test_ws_propagation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/daemon/test_ws_propagation.py
from daemon.telemetry.ws_propagation import inject_trace_context, extract_trace_context


def test_inject_adds_traceparent_to_dict():
    """inject_trace_context adds _traceparent to a dict when a span is active."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    msg = {"type": "poll_opened", "poll": {}}
    with tracer.start_as_current_span("test-span"):
        inject_trace_context(msg)

    assert "_traceparent" in msg
    # W3C traceparent format: 00-<trace_id>-<span_id>-<flags>
    assert msg["_traceparent"].startswith("00-")
    provider.shutdown()


def test_inject_is_noop_without_active_span():
    """inject_trace_context does nothing when no span is active."""
    msg = {"type": "test"}
    inject_trace_context(msg)
    assert "_traceparent" not in msg


def test_extract_returns_context_from_traceparent():
    """extract_trace_context returns a context from _traceparent field."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    # Create a span and inject its context
    msg = {}
    with tracer.start_as_current_span("parent"):
        inject_trace_context(msg)

    # Extract should return a valid context
    ctx = extract_trace_context(msg)
    assert ctx is not None

    # The extracted context should contain a valid span context
    span_ctx = trace.get_current_span(ctx).get_span_context()
    assert span_ctx.trace_id != 0
    provider.shutdown()


def test_extract_returns_none_without_traceparent():
    """extract_trace_context returns None when _traceparent is absent."""
    ctx = extract_trace_context({"type": "test"})
    assert ctx is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `arch -arm64 uv run --extra dev --extra daemon --extra telemetry python -m pytest tests/daemon/test_ws_propagation.py -v --confcutdir=tests/daemon`
Expected: FAIL — `ImportError: cannot import name 'inject_trace_context'`

- [ ] **Step 3: Implement WS propagation helpers**

```python
# daemon/telemetry/ws_propagation.py
"""Inject/extract W3C trace context into/from WS message dicts.

Convention: trace context is carried in the `_traceparent` field
(underscore-prefixed) of JSON message payloads. This field is ignored
by all existing message handlers.
"""
from opentelemetry import context, propagate, trace

_FIELD = "_traceparent"


class _DictSetter:
    def set(self, carrier, key, value):
        if key == "traceparent":
            carrier[_FIELD] = value


class _DictGetter:
    def get(self, carrier, key):
        if key == "traceparent":
            val = carrier.get(_FIELD)
            return [val] if val else []
        return []

    def keys(self, carrier):
        return [_FIELD] if _FIELD in carrier else []


_setter = _DictSetter()
_getter = _DictGetter()


def inject_trace_context(msg: dict) -> None:
    """Inject the current span's trace context into a WS message dict."""
    propagate.inject(msg, setter=_setter)


def extract_trace_context(msg: dict):
    """Extract trace context from a WS message dict. Returns a Context or None."""
    if _FIELD not in msg:
        return None
    return propagate.extract(msg, getter=_getter)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `arch -arm64 uv run --extra dev --extra daemon --extra telemetry python -m pytest tests/daemon/test_ws_propagation.py -v --confcutdir=tests/daemon`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add daemon/telemetry/ws_propagation.py tests/daemon/test_ws_propagation.py
git commit -m "feat(telemetry): add WS trace context inject/extract helpers"
```

---

### Task 3: Instrument daemon WS choke points

**Files:**
- Modify: `daemon/ws_publish.py` (lines 51-55 broadcast, lines 58-67 notify_host)
- Modify: `daemon/proxy_handler.py` (lines 23-69 _process_proxy_request)
- Modify: `daemon/addon_bridge_client.py` (lines 87-95 _send, lines 106-138 _connect_and_listen)

- [ ] **Step 1: Instrument broadcast() in ws_publish.py**

In `daemon/ws_publish.py`, modify `broadcast()` (line 51-55):

```python
def broadcast(msg: BaseModel):
    """Send typed message to all participants via Railway broadcast."""
    if _ws_client is None:
        return
    event = msg.model_dump()
    try:
        from daemon.telemetry.ws_propagation import inject_trace_context
        inject_trace_context(event)
    except ImportError:
        pass
    _ws_client.send({"type": "broadcast", "event": event})
```

- [ ] **Step 2: Instrument notify_host() in ws_publish.py**

Modify `notify_host()` (line 58-67):

```python
async def notify_host(msg: BaseModel):
    """Send typed message to host browser via direct WS."""
    if _host_ws is None:
        return
    try:
        event = msg.model_dump()
        msg_type = event.get("type", "unknown")
        log.debug("host", f"← {msg_type}")
        try:
            from daemon.telemetry.ws_propagation import inject_trace_context
            inject_trace_context(event)
        except ImportError:
            pass
        await _host_ws.send_text(json.dumps(event))
    except Exception:
        log.debug("host", "Failed to send WS message")
```

- [ ] **Step 3: Instrument proxy_handler.py**

In `daemon/proxy_handler.py`, modify `_process_proxy_request()` to extract trace context from the incoming proxy_request and set it as the current context before making the internal HTTP call. Add after `url = ...` (around line 31):

```python
    # Extract trace context from proxy_request (injected by Railway)
    _otel_ctx = None
    try:
        from daemon.telemetry.ws_propagation import extract_trace_context
        _otel_ctx = extract_trace_context(data)
    except ImportError:
        pass

    # If trace context is present, inject it as HTTP headers for the internal call
    if _otel_ctx:
        from opentelemetry import propagate as _propagate
        _propagate.inject(headers, context=_otel_ctx)
```

- [ ] **Step 4: Instrument addon_bridge_client.py send**

In `daemon/addon_bridge_client.py`, modify `_send()` (line 87-95):

```python
    def _send(self, msg: dict) -> bool:
        try:
            from daemon.telemetry.ws_propagation import inject_trace_context
            inject_trace_context(msg)
        except ImportError:
            pass
        with self._ws_lock:
            if self._ws is None:
                return False
            try:
                self._ws.send(json.dumps(msg))
                return True
            except Exception:
                return False
```

- [ ] **Step 5: Instrument addon_bridge_client.py receive**

In `daemon/addon_bridge_client.py`, in `_connect_and_listen()`, after `data = json.loads(raw)` (around line 130), add trace context extraction:

```python
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            # Extract trace context from addons messages
            try:
                from daemon.telemetry.ws_propagation import extract_trace_context
                _ctx = extract_trace_context(data)
                if _ctx:
                    from opentelemetry import context
                    _token = context.attach(_ctx)
            except ImportError:
                _ctx = None
                _token = None
            if data.get("type") == "slide":
                self._slide_queue.put(data)
            if _ctx and _token:
                context.detach(_token)
```

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/ --confcutdir=tests/daemon -x -q --ignore=tests/daemon/test_daemon.py`
Expected: 386+ passed (same as before — OTel imports are guarded by try/except ImportError)

- [ ] **Step 7: Commit**

```bash
git add daemon/ws_publish.py daemon/proxy_handler.py daemon/addon_bridge_client.py
git commit -m "feat(telemetry): instrument daemon WS choke points with trace propagation"
```

---

### Task 4: Instrument Railway proxy bridge

**Files:**
- Modify: `railway/features/ws/proxy_bridge.py` (lines 20-64 proxy_to_daemon)

- [ ] **Step 1: Inject traceparent into proxy_request**

In `railway/features/ws/proxy_bridge.py`, in `proxy_to_daemon()`, after building the `msg` dict (around line 46), add trace context injection:

```python
    msg = {
        "type": "proxy_request",
        "id": req_id,
        "method": method,
        "path": path,
        "body": body.decode("utf-8", errors="replace") if body else None,
        "headers": {k: v for k, v in headers.items()
                    if k.lower() not in ("host", "content-length")},
        "participant_id": participant_id,
    }

    # Inject trace context from the current HTTP request span
    try:
        from daemon.telemetry.ws_propagation import inject_trace_context
        inject_trace_context(msg)
    except ImportError:
        pass
```

- [ ] **Step 2: Run Railway import check**

Run: `arch -arm64 uv run --extra dev python -c "from railway.app import app; print('OK')"`
Expected: OK (the import is inside a try/except, so missing telemetry dep is fine)

- [ ] **Step 3: Commit**

```bash
git add railway/features/ws/proxy_bridge.py
git commit -m "feat(telemetry): inject trace context in Railway proxy bridge"
```

---

### Task 5: Browser OTel SDK initialization

**Files:**
- Create: `static/otel-init.js`
- Modify: `static/participant.html`
- Modify: `static/host.html`

- [ ] **Step 1: Create otel-init.js**

```javascript
// static/otel-init.js
// Browser-side OpenTelemetry initialization.
// Only activates when <meta name="otel-endpoint"> is present in the page.
// Loaded after the OTel CDN scripts in <head>.
(function() {
  'use strict';
  var meta = document.querySelector('meta[name="otel-endpoint"]');
  if (!meta) return; // OTel disabled — no overhead

  var endpoint = meta.getAttribute('content');
  var serviceName = document.querySelector('meta[name="otel-service-name"]');
  serviceName = serviceName ? serviceName.getAttribute('content') : 'Browser';

  // --- Provider setup ---
  var provider = new opentelemetry.sdk.trace.web.WebTracerProvider();

  // Simple exporter: POST spans to Railway endpoint
  var OtelBatchExporter = {
    _batch: [],
    _timer: null,
    export: function(spans, resultCallback) {
      for (var i = 0; i < spans.length; i++) {
        this._batch.push(_spanToJson(spans[i]));
      }
      if (!this._timer) {
        this._timer = setTimeout(this._flush.bind(this), 2000);
      }
      resultCallback({ code: 0 }); // SUCCESS
    },
    _flush: function() {
      this._timer = null;
      if (!this._batch.length) return;
      var payload = JSON.stringify(this._batch);
      this._batch = [];
      navigator.sendBeacon(endpoint, payload);
    },
    shutdown: function() { this._flush(); }
  };

  function _spanToJson(span) {
    var ctx = span.spanContext();
    return {
      name: span.name,
      trace_id: ctx.traceId,
      span_id: ctx.spanId,
      parent_span_id: span.parentSpanId || '',
      start_time: span.startTime,
      end_time: span.endTime,
      attributes: span.attributes || {},
      resource: { 'service.name': serviceName }
    };
  }

  provider.addSpanProcessor(
    new opentelemetry.sdk.trace.web.SimpleSpanProcessor(OtelBatchExporter)
  );
  provider.register();

  // --- Fetch instrumentation ---
  var fetchInstrumentation = new opentelemetry.instrumentation.fetch.FetchInstrumentation({
    propagateTraceHeaderCorsUrls: [/.*/],  // inject traceparent into all requests
    clearTimingResources: false,
  });
  fetchInstrumentation.setTracerProvider(provider);
  fetchInstrumentation.enable();

  // --- WS trace context ---
  // Store the latest _traceparent from WS messages. Fetch instrumentation
  // uses it as parent context for subsequent REST calls.
  window._otelWsTraceparent = null;

  window._otelExtractWsTrace = function(msg) {
    if (msg && msg._traceparent) {
      window._otelWsTraceparent = msg._traceparent;
    }
  };

  console.log('[otel] Browser tracing initialized, service=' + serviceName);
})();
```

- [ ] **Step 2: Add CDN scripts and otel-init.js to participant.html**

In `static/participant.html`, add before the closing `</head>` tag (after the existing CDN scripts):

```html
  <!-- OpenTelemetry (conditional — activated by meta tag) -->
  <script src="https://cdn.jsdelivr.net/npm/@opentelemetry/api@1/build/bundles/opentelemetry-api.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@opentelemetry/sdk-trace-web@1/build/bundles/opentelemetry-sdk-trace-web.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@opentelemetry/instrumentation-fetch@0/build/bundles/opentelemetry-instrumentation-fetch.min.js"></script>
  <script src="/static/otel-init.js"></script>
```

- [ ] **Step 3: Add the same CDN scripts to host.html**

Same block added to `static/host.html` before `</head>`.

- [ ] **Step 4: Hook WS message receive into OTel context extraction**

In `static/participant.js`, in the `ws.onmessage` handler (around line 3024), add after `const msg = JSON.parse(event.data)`:

```javascript
    if (window._otelExtractWsTrace) window._otelExtractWsTrace(msg);
```

In `static/host.js`, in the `ws.onmessage` handler (around line 295), add after `const msg = JSON.parse(e.data)`:

```javascript
    if (window._otelExtractWsTrace) window._otelExtractWsTrace(msg);
```

- [ ] **Step 5: Commit**

```bash
git add static/otel-init.js static/participant.html static/host.html static/participant.js static/host.js
git commit -m "feat(telemetry): add browser OTel SDK with fetch instrumentation and WS context"
```

---

### Task 6: Railway telemetry span receiver endpoint

**Files:**
- Create: `railway/features/telemetry/__init__.py`
- Create: `railway/features/telemetry/router.py`
- Modify: `railway/app.py`

- [ ] **Step 1: Create the span receiver endpoint**

```python
# railway/features/telemetry/__init__.py
```

```python
# railway/features/telemetry/router.py
"""Receive browser OTel spans and append to the shared traces file."""
import json
import os
import threading
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

_traces_file = os.environ.get("OTEL_TRACES_FILE")
_lock = threading.Lock()


@router.post("/spans", status_code=204)
async def receive_spans(request: Request):
    """Receive browser spans as JSON array and append to traces file."""
    if not _traces_file:
        return Response(status_code=204)
    body = await request.body()
    try:
        spans = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return Response(status_code=400)
    if not isinstance(spans, list):
        return Response(status_code=400)
    with _lock:
        with open(_traces_file, "a", encoding="utf-8") as f:
            for span in spans:
                f.write(json.dumps(span) + "\n")
    return Response(status_code=204)
```

- [ ] **Step 2: Register the router in railway/app.py**

In `railway/app.py`, add the telemetry router registration (conditionally, when OTEL is enabled):

```python
# After existing router registrations
import os
if os.environ.get("OTEL_TRACES_FILE"):
    from railway.features.telemetry.router import router as telemetry_router
    app.include_router(telemetry_router)
```

- [ ] **Step 3: Run Railway import check**

Run: `arch -arm64 uv run --extra dev python -c "import os; os.environ['OTEL_TRACES_FILE']='/tmp/test.jsonl'; from railway.app import app; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add railway/features/telemetry/__init__.py railway/features/telemetry/router.py railway/app.py
git commit -m "feat(telemetry): add browser span receiver endpoint on Railway"
```

---

### Task 7: Trace-to-PlantUML generator

**Files:**
- Create: `scripts/traces_to_puml.py`
- Test: `tests/daemon/test_traces_to_puml.py`

- [ ] **Step 1: Write tests for the generator**

```python
# tests/daemon/test_traces_to_puml.py
import json
import tempfile
from pathlib import Path


def _write_spans(path, spans):
    Path(path).write_text("\n".join(json.dumps(s) for s in spans) + "\n")


def _make_span(name, service, trace_id="aaa", span_id="s1", parent_span_id="",
               attributes=None, start_time=1000, end_time=2000):
    return {
        "name": name,
        "resource": {"service.name": service},
        "context": {"trace_id": trace_id, "span_id": span_id},
        "parent_id": parent_span_id,
        "start_time": start_time,
        "end_time": end_time,
        "attributes": attributes or {},
    }


def test_basic_cross_service_arrows():
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/poll/vote", "Participant", span_id="s1",
                    start_time=1000, attributes={"trace.family": "poll"}),
        _make_span("POST /api/poll/vote", "Daemon", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"trace.family": "poll"}),
    ])

    generate_puml(path, family="poll", output=out)
    content = Path(out).read_text()

    assert "participant Participant" in content or "Participant" in content
    assert "Daemon" in content
    assert "POST /api/poll/vote" in content
    assert "@startuml" in content
    assert "@enduml" in content


def test_skip_internal_spans():
    """Spans where parent and child share the same service are omitted."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/poll", "Host", span_id="s1",
                    start_time=1000, attributes={"trace.family": "test"}),
        _make_span("POST /api/poll", "Daemon", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"trace.family": "test"}),
        _make_span("create_poll", "Daemon", span_id="s3", parent_span_id="s2",
                    start_time=1002, attributes={"trace.family": "test"}),
    ])

    generate_puml(path, family="test", output=out)
    content = Path(out).read_text()

    # Internal Daemon→Daemon span should be skipped
    assert "create_poll" not in content
    # Cross-service Host→Daemon should be present
    assert "POST /api/poll" in content


def test_collapse_proxy_chain():
    """Railway proxy intermediary should be collapsed: Participant→Railway→Daemon becomes Participant→Daemon."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/participant/poll/vote", "Participant", span_id="s1",
                    start_time=1000, attributes={"trace.family": "proxy"}),
        _make_span("proxy_request", "Railway", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"proxy.path": "/api/participant/poll/vote",
                                                  "trace.family": "proxy"}),
        _make_span("POST /api/participant/poll/vote", "Daemon", span_id="s3", parent_span_id="s2",
                    start_time=1002, attributes={"trace.family": "proxy"}),
    ])

    generate_puml(path, family="proxy", output=out)
    content = Path(out).read_text()

    # Railway should not appear as intermediary
    assert "Railway" not in content
    # Direct arrow from Participant to Daemon
    assert "Participant" in content
    assert "Daemon" in content


def test_collapse_broadcast_relay():
    """Daemon broadcast via Railway should collapse: Daemon→Railway→Participant becomes Daemon→Participant."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("broadcast:poll_opened", "Daemon", span_id="s1",
                    start_time=1000, attributes={"trace.family": "bcast"}),
        _make_span("broadcast_fanout", "Railway", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"trace.family": "bcast"}),
        _make_span("ws_receive:poll_opened", "Participant", span_id="s3", parent_span_id="s2",
                    start_time=1002, attributes={"trace.family": "bcast"}),
    ])

    generate_puml(path, family="bcast", output=out)
    content = Path(out).read_text()

    # Railway should not appear
    assert "Railway" not in content
    # Direct arrow from Daemon to Participant
    assert "Daemon" in content
    assert "Participant" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_traces_to_puml.py -v --confcutdir=tests/daemon`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.traces_to_puml'`

- [ ] **Step 3: Implement the generator**

```python
# scripts/traces_to_puml.py
"""Generate PlantUML sequence diagrams from OTel trace JSONL files.

Generic transformation rules:
1. Collapse proxy chains (A → Railway → Daemon → A → Daemon)
2. Collapse broadcast relay (Daemon → Railway → Browser → Daemon → Browser)
3. Participant names from service.name attribute
4. Arrow labels from span names
5. Skip internal spans (same service parent→child)
"""
import json
import sys
from pathlib import Path


def _load_spans(traces_path: str, family: str) -> list[dict]:
    """Load spans from JSONL file, filtered by trace.family attribute."""
    spans = []
    for line in Path(traces_path).read_text().strip().split("\n"):
        if not line.strip():
            continue
        span = json.loads(line)
        attrs = span.get("attributes", {})
        if family and attrs.get("trace.family") != family:
            continue
        spans.append(span)
    return spans


def _service_name(span: dict) -> str:
    resource = span.get("resource", {})
    return resource.get("service.name", resource.get("service_name", "Unknown"))


def _span_id(span: dict) -> str:
    ctx = span.get("context", {})
    return ctx.get("span_id", span.get("span_id", ""))


def _parent_id(span: dict) -> str:
    return span.get("parent_id", span.get("parent_span_id", ""))


def _build_span_index(spans: list[dict]) -> dict[str, dict]:
    return {_span_id(s): s for s in spans if _span_id(s)}


def _extract_edges(spans: list[dict]) -> list[tuple[str, str, str, int]]:
    """Extract (from_service, to_service, label, start_time) edges from spans.

    An edge exists when a child span has a different service.name than its parent.
    """
    index = _build_span_index(spans)
    edges = []
    for span in spans:
        pid = _parent_id(span)
        if not pid or pid not in index:
            continue
        parent = index[pid]
        from_svc = _service_name(parent)
        to_svc = _service_name(span)
        if from_svc == to_svc:
            continue  # Rule 5: skip internal spans
        label = span.get("name", "unknown")
        start = span.get("start_time", 0)
        edges.append((from_svc, to_svc, label, start))
    return edges


def _collapse_proxy(edges: list[tuple]) -> list[tuple]:
    """Rule 1: Collapse A→Railway→Daemon into A→Daemon when Railway is pure proxy."""
    result = []
    skip = set()
    for i, (f, t, label, ts) in enumerate(edges):
        if i in skip:
            continue
        if t == "Railway" and label == "proxy_request":
            # Find the next edge from Railway to Daemon
            for j in range(i + 1, len(edges)):
                f2, t2, label2, ts2 = edges[j]
                if f2 == "Railway" and t2 == "Daemon":
                    # Collapse: use the Daemon edge's label with original source
                    result.append((f, "Daemon", label2, ts))
                    skip.add(j)
                    break
            else:
                result.append((f, t, label, ts))
        else:
            result.append((f, t, label, ts))
    return result


def _collapse_broadcast(edges: list[tuple]) -> list[tuple]:
    """Rule 2: Collapse Daemon→Railway→Browser into Daemon→Browser for broadcasts."""
    result = []
    skip = set()
    for i, (f, t, label, ts) in enumerate(edges):
        if i in skip:
            continue
        if f == "Daemon" and t == "Railway" and "broadcast" in label:
            # Find next edge from Railway to a browser actor
            for j in range(i + 1, len(edges)):
                f2, t2, label2, ts2 = edges[j]
                if f2 == "Railway" and t2 not in ("Daemon", "Railway"):
                    result.append(("Daemon", t2, label, ts))
                    skip.add(j)
                    break
            else:
                result.append((f, t, label, ts))
        else:
            result.append((f, t, label, ts))
    return result


def _deduplicate_edges(edges: list[tuple]) -> list[tuple]:
    """Remove duplicate (from, to, label) tuples, keeping first occurrence order."""
    seen = set()
    result = []
    for f, t, label, ts in edges:
        key = (f, t, label)
        if key not in seen:
            seen.add(key)
            result.append((f, t, label, ts))
    return result


def generate_puml(traces_path: str, family: str, output: str) -> None:
    """Generate a PlantUML sequence diagram from collected traces."""
    spans = _load_spans(traces_path, family)
    if not spans:
        Path(output).write_text("@startuml\nnote over Daemon: No traces found for family '{}'\n@enduml\n".format(family))
        return

    edges = _extract_edges(spans)
    edges.sort(key=lambda e: e[3])  # sort by start_time
    edges = _collapse_proxy(edges)
    edges = _collapse_broadcast(edges)
    edges = _deduplicate_edges(edges)

    # Collect participant names in order of first appearance
    participants = []
    seen_p = set()
    for f, t, _, _ in edges:
        for p in (f, t):
            if p not in seen_p:
                seen_p.add(p)
                participants.append(p)

    lines = ["@startuml"]
    lines.append("hide footbox")
    lines.append("")
    for p in participants:
        lines.append(f'participant "{p}"')
    lines.append("")
    for f, t, label, _ in edges:
        lines.append(f'"{f}" -> "{t}": {label}')
    lines.append("")
    lines.append("@enduml")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: traces_to_puml.py <traces.jsonl> <family> <output.puml>")
        sys.exit(1)
    generate_puml(sys.argv[1], sys.argv[2], sys.argv[3])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_traces_to_puml.py -v --confcutdir=tests/daemon`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/traces_to_puml.py tests/daemon/test_traces_to_puml.py
git commit -m "feat(telemetry): add trace-to-PlantUML generator with proxy/broadcast collapsing"
```

---

### Task 8: Hermetic test infrastructure changes

**Files:**
- Modify: `tests/docker/Dockerfile.hermetic`
- Modify: `tests/docker/start_hermetic.sh`

- [ ] **Step 1: Add OTel packages to Dockerfile.hermetic**

Add after the existing `RUN pip install ...` line:

```dockerfile
RUN pip install opentelemetry-distro opentelemetry-api opentelemetry-sdk \
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-urllib && \
    opentelemetry-bootstrap -a install
```

- [ ] **Step 2: Modify start_hermetic.sh for OTel**

Add env vars after the existing exports (around line 27):

```bash
# OpenTelemetry
export OTEL_TRACES_FILE=/tmp/traces.jsonl
export OTEL_SDK_DISABLED=false
```

Change the Railway startup (line 87) from:

```bash
python -m uvicorn railway.app:app --host 0.0.0.0 --port 8000 &
```

to:

```bash
OTEL_SERVICE_NAME=Railway opentelemetry-instrument python -m uvicorn railway.app:app --host 0.0.0.0 --port 8000 &
```

Change the daemon startup (line 100) from:

```bash
python -m daemon &
```

to:

```bash
OTEL_SERVICE_NAME=Daemon opentelemetry-instrument python -m daemon &
```

- [ ] **Step 3: Commit**

```bash
git add tests/docker/Dockerfile.hermetic tests/docker/start_hermetic.sh
git commit -m "feat(telemetry): enable OTel auto-instrumentation in hermetic test environment"
```

---

### Task 9: Hermetic test — sequence extraction

**Files:**
- Create: `tests/docker/test_sequence_extraction.py`

- [ ] **Step 1: Write the hermetic test for poll sequence extraction**

```python
# tests/docker/test_sequence_extraction.py
"""
Hermetic E2E test: Extract sequence diagram from OTel traces and compare
against the hand-written PlantUML diagram.

Tagged @pytest.mark.nightly — runs in nightly CI only.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest  # noqa: I001
from playwright.sync_api import expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
TRACES_FILE = os.environ.get("OTEL_TRACES_FILE", "/tmp/traces.jsonl")


@pytest.mark.nightly
def test_poll_sequence_diagram_extraction():
    """Exercise poll flow, extract sequence diagram from traces, compare with hand-written."""
    # Clear traces
    Path(TRACES_FILE).write_text("")

    session_id = fresh_session("SeqPoll")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_raw)

        # Participant
        pax_ctx = browser.new_context()
        pax_raw = pax_ctx.new_page()
        pax_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_raw)
        pax.join("Alice")

        # Exercise poll flow
        host.create_poll("What is 1+1?", ["1", "2", "3"])
        expect(pax._page.locator("#content h2")).to_have_text("What is 1+1?", timeout=5000)

        pax.vote_for("2")

        host.close_poll()
        expect(pax._page.locator(".closed-banner")).to_be_visible(timeout=5000)

        host.reveal_correct(["B"])
        pax._page.wait_for_timeout(1000)

        browser.close()

    # Wait a moment for spans to flush
    import time
    time.sleep(2)

    # Generate PlantUML from traces
    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/tmp/generated-03-poll-and-quiz.puml"
    generate_puml(TRACES_FILE, family="poll", output=output_path)

    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)

    # Basic structural checks (the generated diagram should contain key interactions)
    assert "@startuml" in generated
    assert "Daemon" in generated or "Host" in generated
    # The diagram should have at least some arrows
    assert "->" in generated

    print("SUCCESS: Sequence diagram extracted from traces")
```

- [ ] **Step 2: Commit**

```bash
git add tests/docker/test_sequence_extraction.py
git commit -m "test(telemetry): add hermetic test for poll sequence diagram extraction"
```

---

### Task 10: Create generated sequences output directory and gitignore

**Files:**
- Create: `docs/sequences/generated/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Create output directory**

```bash
mkdir -p docs/sequences/generated
touch docs/sequences/generated/.gitkeep
```

- [ ] **Step 2: Add generated diagrams to .gitignore**

Add to `.gitignore`:

```
# Generated sequence diagrams (from OTel traces)
docs/sequences/generated/*.puml
```

The `.gitkeep` ensures the directory exists; the generated `.puml` files are not committed (they're test artifacts).

- [ ] **Step 3: Commit**

```bash
git add docs/sequences/generated/.gitkeep .gitignore
git commit -m "chore: add generated sequences output directory"
```

---

### Task 11: Compare generated diagrams and improve observability

**Files:**
- Various daemon/railway files (determined by comparison results)

This task is exploratory — the implementing agent performs it after Task 9 runs successfully.

- [ ] **Step 1: Read the generated diagram**

Read the generated `.puml` from `docs/sequences/generated/03-poll-and-quiz.puml` (output of the hermetic test in Task 9).

- [ ] **Step 2: Read the hand-written diagram**

Read the existing `docs/sequences/03-poll-and-quiz.puml`.

- [ ] **Step 3: Identify 3-5 differences**

Compare the two diagrams structurally. Look for:
- Arrows present in the hand-written diagram but missing from the generated one (suggests missing spans or insufficient instrumentation)
- Actors in the hand-written diagram that don't appear in the generated one
- Arrow labels that are too generic in the generated diagram (e.g., `POST /api/participant/poll/vote` vs the hand-written `proxy vote request`)

Document each difference.

- [ ] **Step 4: Fix differences by adding instrumentation**

For each identified difference, add targeted observability to make the generated diagram closer to the hand-written one. Examples of fixes:
- Add a custom span with a descriptive name at a key code point (e.g., `with tracer.start_as_current_span("cast_vote"):`)
- Add span attributes that the generator can use for better labels
- Add spans at the broadcast fan-out point to show which actors receive the message

Each fix should be a small, focused change — a span creation or attribute addition, not structural refactoring.

- [ ] **Step 5: Re-run hermetic test and verify improvement**

Re-run the hermetic test from Task 9. Read the regenerated diagram and confirm the differences are resolved or reduced.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(telemetry): improve observability to align generated diagrams with hand-written ones"
```

---

## Execution Notes

**Task dependencies:** Tasks 1-2 are foundational (exporter + helpers). Tasks 3-4 depend on Task 2 (WS propagation). Tasks 5-6 are independent (browser + Railway endpoint). Task 7 is independent (generator). Task 8 depends on all previous tasks. Task 9 depends on Task 8. Task 10 is independent. Task 11 depends on Task 9.

**Parallel execution:** Tasks 3+4, 5+6, 7, and 10 can each run in parallel once their dependencies are met.

**Testing strategy:** Tasks 1-2 and 7 have unit tests that run locally. Tasks 8-9 require the Docker hermetic environment. The OTel imports in production code are guarded by `try/except ImportError` so existing tests pass without the telemetry dependency installed.
