# OTel Sequence Diagram Extraction from Hermetic Tests

**Date:** 2026-04-12
**Status:** Approved design

## Goal

Instrument the system with OpenTelemetry tracing across all 5 actors (Participant browser, Host browser, Railway, Daemon, macOS Addons mock), collect traces during hermetic E2E tests, and extract PlantUML sequence diagrams from them. Compare generated diagrams against the existing 8 hand-written `.puml` files to detect architectural drift.

Secondary goal: demonstrate OTel distributed tracing in a real system during workshops. The same instrumentation becomes production-ready when Grafana/Tempo is added later.

## Actors and Communication Channels

```
Participant Browser ──HTTP──▶ Railway ──WS──▶ Daemon ◀──WS──▶ macOS Addons
Host Browser ──HTTP──▶ Daemon ────WS───▶ Railway ──WS──▶ Participant Browser
```

Five actors:

| Actor | Process | Connection to others |
|-------|---------|---------------------|
| Participant browser | Playwright browser in tests | HTTP REST to Railway, WS from Railway |
| Host browser | Playwright browser in tests | HTTP REST to Daemon (localhost:1234), WS from Railway |
| Railway | FastAPI on port 8000 | HTTP from participants, WS to/from Daemon, WS to browsers |
| Daemon | FastAPI on port 1234 | HTTP from host, WS to/from Railway, WS to/from Addons |
| macOS Addons | Mock WS server in tests | WS to/from Daemon on port 8765 |

Six communication channels requiring trace propagation:

1. Participant → Railway (HTTP): auto-instrumented
2. Railway → Daemon (WS proxy_request/response): manual
3. Daemon → Railway (WS broadcast): manual
4. Railway → browsers (WS fan-out): pass-through
5. Host → Daemon (HTTP): auto-instrumented
6. Daemon ↔ Addons (WS bidirectional): manual

## OTel SDK Setup per Actor

### Python backends (Railway + Daemon)

**Dependencies (added to pyproject.toml `[project.optional-dependencies]`):**
- `opentelemetry-distro`
- `opentelemetry-instrumentation-fastapi`
- `opentelemetry-instrumentation-urllib`
- `opentelemetry-api`
- `opentelemetry-sdk`

**Startup:** Wrap with `opentelemetry-instrument`:
- Railway: `opentelemetry-instrument python -m uvicorn railway.app:app --host 0.0.0.0 --port 8000`
- Daemon: `opentelemetry-instrument python -m daemon`

**Auto-instrumented:** FastAPI HTTP request/response spans, `urllib.request` outgoing calls.

**Custom FileSpanExporter:** A `SpanExporter` subclass (~20 lines) that appends one JSON line per completed span to a configurable file path. Uses `SimpleSpanProcessor` (not batch) to avoid timing issues in tests.

**Env vars:**
- `OTEL_SDK_DISABLED=true` by default (off in production until Grafana is added)
- `OTEL_TRACES_FILE=/tmp/traces.jsonl` — path for the file exporter
- `OTEL_SERVICE_NAME=Railway` or `Daemon`

### Browser (Participant + Host)

**Loading:** OTel JS SDK via CDN `<script>` tags in `participant.html` and `host.html` `<head>`:
- `@opentelemetry/api`
- `@opentelemetry/sdk-trace-web`
- `@opentelemetry/instrumentation-fetch`

These are available as UMD bundles on jsDelivr, consistent with the existing d3/qrcode/marked CDN pattern.

**Auto-instrumented:** `fetch()` calls — the SDK auto-injects `traceparent` header into all outgoing HTTP requests.

**WS context:** On receiving a WS message containing `_traceparent`, store it. The fetch instrumentation uses it as parent context for subsequent REST calls triggered by that message.

**Span export:** Spans sent via `POST /api/telemetry/spans` to Railway, which appends them to the same `OTEL_TRACES_FILE`.

**Feature flag:** OTel JS initialization is gated on a `<meta name="otel-endpoint" content="...">` tag, injected by Railway only when `OTEL_SDK_DISABLED` is not `true`. When absent, no SDK initialization, zero overhead.

### macOS Addons mock (hermetic tests only)

The mock WS server in `tests/docker/` creates manual OTel spans:
- On sending a slide event: create a span, inject `_traceparent` into the message JSON
- On receiving an emoji/session message: extract `_traceparent`, create a child span
- Uses the same `FileSpanExporter`

**`OTEL_SERVICE_NAME=Addons`**

## Manual WS Trace Propagation

Five choke points, ~40 lines total. All use the standard OTel `propagate.inject()`/`propagate.extract()` API.

**Convention:** The field `_traceparent` (underscore-prefixed) is added to WS message JSON payloads at the dict level, after `model_dump()`. No Pydantic model changes. All existing handlers ignore unknown fields.

### 1. `daemon/ws_publish.py` — `broadcast()` (~5 lines)

```python
def broadcast(msg: BaseModel):
    if _ws_client is None:
        return
    event = msg.model_dump()
    # Inject trace context into the event dict
    propagate.inject(event, setter=_dict_setter)
    _ws_client.send({"type": "broadcast", "event": event})
```

### 2. `daemon/ws_publish.py` — `notify_host()` (~5 lines)

Same pattern — inject `_traceparent` into the message dict before sending.

### 3. `railway/features/ws/proxy_bridge.py` — `proxy_to_daemon()` (~5 lines)

Extract `traceparent` from the incoming HTTP request (already present from browser fetch instrumentation), add it to the `proxy_request` dict sent to daemon over WS.

### 4. `daemon/proxy_handler.py` — receiving proxy_request (~8 lines)

Extract `_traceparent` from the proxy_request dict, create a child span linked to the incoming trace, set as current context before making the internal HTTP call.

### 5. `daemon/addon_bridge_client.py` — send/receive (~8 lines)

On `send()`: inject `_traceparent` into outgoing JSON. On receive (slide events drained in `__main__.py`): extract `_traceparent`, create child span.

## Span Collection

### FileSpanExporter (new file: `daemon/telemetry/file_exporter.py`)

```python
class FileSpanExporter(SpanExporter):
    def __init__(self, path: str):
        self._path = path

    def export(self, spans):
        with open(self._path, "a") as f:
            for span in spans:
                f.write(span.to_json() + "\n")
        return SpanExportResult.SUCCESS
```

Configured via `OTEL_TRACES_FILE` env var. When not set, no file export (production default).

### Browser span receiver (new Railway endpoint)

`POST /api/telemetry/spans` — public endpoint (no auth), accepts JSON array of span objects, appends to `OTEL_TRACES_FILE`. Only registered when `OTEL_SDK_DISABLED` is not `true`.

## Trace-to-PlantUML Generator

**New file:** `scripts/traces_to_puml.py`

### Input
- `/tmp/traces.jsonl` — one JSON span per line
- Behavior family tag (from span attribute `trace.family` set by the test)

### Generic transformation rules (no domain-specific mappings)

**Rule 1 — Collapse proxy chains:** When a span sequence shows `A → Railway → Daemon` where Railway's role is pure forwarding (proxy_request/response pattern), collapse to `A → Daemon`. Detected generically: Railway span has a single child on Daemon with the same HTTP path. Arrow label: original HTTP method + path.

**Rule 2 — Collapse broadcast relay:** When `Daemon → Railway → Browser` where Railway's role is WS fan-out, collapse to `Daemon → Browser`. Detected generically: Railway span receives a broadcast event and sends identical content to connected clients. Arrow label: WS message type from the event.

**Rule 3 — Participant names from `service.name`:** No mapping dict. `OTEL_SERVICE_NAME` values (`Participant`, `Host`, `Railway`, `Daemon`, `Addons`) become PlantUML participant names directly.

**Rule 4 — Arrow labels from span names:** Span name (e.g., `POST /api/participant/poll/vote`, `broadcast:poll_opened`, `ws:slide`) becomes the arrow label. No renaming.

**Rule 5 — Skip internal spans:** When parent and child span share the same `service.name`, omit from the diagram. Only cross-service arrows shown.

### Output

PlantUML files written to `docs/sequences/generated/<NN>-<family>.puml`.

### Aggregation

Multiple traces tagged with the same `trace.family` are merged into one diagram: union of observed cross-service interactions, ordered by first occurrence timestamp.

## Comparison with Existing Diagrams

A test parses both generated and hand-written `.puml` files, extracts `(from, to, label)` tuples representing each arrow, and compares:

- **Participants match:** same set of actor names (after applying the same proxy/broadcast collapsing to the hand-written diagrams mentally — the hand-written ones already omit Railway proxy for most flows)
- **Arrows match:** structural comparison allowing the generated diagram to be a superset (it may capture more detail than the hand-written one)
- **Missing arrows flagged:** if the hand-written diagram has an arrow not seen in any trace, that's a drift warning

The comparison is structural, not textual — whitespace, comments, PlantUML styling directives are ignored.

## Hermetic Test Integration

### `start_hermetic.sh` changes

Before Railway and daemon start:
```bash
export OTEL_SDK_DISABLED=false
export OTEL_TRACES_FILE=/tmp/traces.jsonl
```

Railway startup:
```bash
OTEL_SERVICE_NAME=Railway opentelemetry-instrument python -m uvicorn railway.app:app --host 0.0.0.0 --port 8000 &
```

Daemon startup:
```bash
OTEL_SERVICE_NAME=Daemon opentelemetry-instrument python -m daemon &
```

### Test fixture

```python
@pytest.fixture
def trace_session():
    traces_file = Path("/tmp/traces.jsonl")
    traces_file.write_text("")  # clear previous traces
    yield traces_file
```

### Diagram-generating tests

Specific hermetic tests exercise canonical flows and generate diagrams after assertions pass:

```python
from scripts.traces_to_puml import generate_puml

def test_poll_flow_generates_sequence(trace_session):
    # ... exercise full poll lifecycle ...
    generate_puml(trace_session, family="03-poll-and-quiz",
                  output="docs/sequences/generated/03-poll-and-quiz.puml")
```

### Initial coverage (2-3 families)

| Family | Existing test | `.puml` file |
|--------|--------------|--------------|
| Poll and quiz | `test_poll_flow.py` | `03-poll-and-quiz.puml` |
| Participant join | `test_participant_join_flow.py` | `02-participant-join.puml` |
| Slides follow-me | `test_follow_me.py` | `06-slides.puml` |

Remaining 5 families added incrementally.

## Out of Scope

- Production Grafana/Tempo — added later with OTLP exporter swap
- Metrics — traces only
- Automatic CI enforcement — comparison test is `@pytest.mark.nightly`
- Changes to existing hand-written `.puml` files
- OTel Collector process — direct file export instead
- Pydantic model changes — `_traceparent` injected at dict level
- Changes to `static/work-hours.js`
- Coverage of all 8 behavior families — start with 3, extend later

## New Files

| File | Purpose |
|------|---------|
| `daemon/telemetry/__init__.py` | OTel setup: FileSpanExporter, propagation helpers |
| `daemon/telemetry/file_exporter.py` | FileSpanExporter implementation |
| `railway/features/telemetry/router.py` | `POST /api/telemetry/spans` endpoint |
| `static/otel-init.js` | Browser OTel SDK initialization (shared by participant + host) |
| `scripts/traces_to_puml.py` | Trace-to-PlantUML generator with generic transformation rules |
| `tests/docker/test_sequence_extraction.py` | Hermetic tests that generate + compare diagrams |

## Dependencies Added

**Python (pyproject.toml):**
- `opentelemetry-distro`
- `opentelemetry-instrumentation-fastapi`
- `opentelemetry-instrumentation-urllib`
- `opentelemetry-api`
- `opentelemetry-sdk`

**Browser (CDN):**
- `@opentelemetry/api` (UMD bundle)
- `@opentelemetry/sdk-trace-web` (UMD bundle)
- `@opentelemetry/instrumentation-fetch` (UMD bundle)
