# Daemon ↔ Railway API Documentation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the internal daemon↔railway WS control messages and REST endpoints with spec files, contract tests, and generated API.md sections — matching the existing host/participant documentation pattern.

**Architecture:** Two new spec files (`docs/railway-openapi.yaml` + `docs/railway-ws.yaml`) follow existing OpenAPI/AsyncAPI patterns. Contract tests validate specs against source code. The generator script gains two new CLI args and renders "Daemon REST" / "Daemon WS" subsections per feature. A new `infrastructure` feature covers transport plumbing.

**Tech Stack:** YAML (OpenAPI 3.1.0, AsyncAPI 2.6.0), Python (pytest), existing `scripts/generate_apis_md.py`

---

### Task 1: Create `docs/railway-ws.yaml` — AsyncAPI Spec for Daemon ↔ Railway WS

**Files:**
- Create: `docs/railway-ws.yaml`
- Modify: `docs/api-reference-features.md` (add `infrastructure` feature)

- [ ] **Step 1: Create the AsyncAPI spec file**

```yaml
# docs/railway-ws.yaml
asyncapi: '2.6.0'
info:
  title: Training Assistant — Daemon ↔ Railway WebSocket Protocol
  version: '1.0'
  description: |
    Internal WebSocket control channel between daemon (trainer's Mac) and Railway backend.
    Connection: ws://{railway_host}/ws/daemon (Basic Auth).
    Two directions: "subscribe" = messages the daemon receives from Railway,
    "publish" = messages the daemon sends to Railway.

channels:
  /ws/daemon:
    subscribe:
      summary: Messages Railway sends TO the daemon
      message:
        oneOf:
          - $ref: '#/components/messages/participant_presence'
          - $ref: '#/components/messages/daemon_state_push'
          - $ref: '#/components/messages/sync_files'
          - $ref: '#/components/messages/download_pdf'
          - $ref: '#/components/messages/pdf_download_complete'
          - $ref: '#/components/messages/file_ready_for_download'
          - $ref: '#/components/messages/summary_force'
          - $ref: '#/components/messages/summary_full_reset'
          - $ref: '#/components/messages/scores_reset'
          - $ref: '#/components/messages/proxy_request'
    publish:
      summary: Messages the daemon sends TO Railway
      message:
        oneOf:
          - $ref: '#/components/messages/set_session_id'
          - $ref: '#/components/messages/code_timestamp'
          - $ref: '#/components/messages/broadcast'
          - $ref: '#/components/messages/send_to_host'
          - $ref: '#/components/messages/proxy_response'
          - $ref: '#/components/messages/daemon_ping'
          - $ref: '#/components/messages/slide_invalidated'

components:
  messages:
    # --- Railway → Daemon (subscribe) ---

    participant_presence:
      summary: Participant came online or went offline
      x-feature: identity
      payload:
        type: object
        required: [type, uuid, online]
        properties:
          type:
            enum: [participant_presence]
          uuid:
            type: string
            description: Participant UUID
          online:
            type: boolean

    daemon_state_push:
      summary: Full runtime state snapshot sent on daemon reconnect
      x-feature: identity
      payload:
        type: object
        required: [type, online_participants]
        properties:
          type:
            enum: [daemon_state_push]
          online_participants:
            type: array
            items:
              type: string
            description: UUIDs of currently connected participants

    sync_files:
      summary: Static file hashes and PDF slugs for cache sync
      x-feature: slides
      payload:
        type: object
        required: [type, static_hashes, pdf_slugs]
        properties:
          type:
            enum: [sync_files]
          static_hashes:
            type: object
            additionalProperties:
              type: string
            description: Map of static file path → content hash
          pdf_slugs:
            type: object
            additionalProperties:
              type: string
            description: Map of PDF slug → content hash

    download_pdf:
      summary: Request daemon to download a slide PDF from Google Drive via Railway
      x-feature: slides
      x-doc-notes:
        - "Legacy flow: Railway tells daemon to trigger PDF download"
      payload:
        type: object
        required: [type, slug, drive_export_url]
        properties:
          type:
            enum: [download_pdf]
          slug:
            type: string
          drive_export_url:
            type: string

    pdf_download_complete:
      summary: PDF download finished (success or error)
      x-feature: slides
      payload:
        type: object
        required: [type, slug, status]
        properties:
          type:
            enum: [pdf_download_complete]
          slug:
            type: string
          status:
            type: string
            enum: [ok, error]
          error:
            type: string
            description: Error message (present when status=error)

    file_ready_for_download:
      summary: Uploaded file is ready for daemon to download
      x-feature: paste_upload
      payload:
        type: object
        required: [type, file_id, uuid, filename, size, session_id]
        properties:
          type:
            enum: [file_ready_for_download]
          file_id:
            type: integer
          uuid:
            type: string
            description: Uploader's participant UUID
          filename:
            type: string
          size:
            type: integer
            description: File size in bytes
          session_id:
            type: string

    summary_force:
      summary: Force regeneration of the session summary
      x-feature: notes_summary
      payload:
        type: object
        required: [type]
        properties:
          type:
            enum: [summary_force]

    summary_full_reset:
      summary: Reset summary state and regenerate from scratch
      x-feature: notes_summary
      payload:
        type: object
        required: [type]
        properties:
          type:
            enum: [summary_full_reset]

    scores_reset:
      summary: Reset all participant scores to zero
      x-feature: scores_leaderboard
      payload:
        type: object
        required: [type]
        properties:
          type:
            enum: [scores_reset]

    proxy_request:
      summary: HTTP request proxied from Railway to daemon's local FastAPI
      x-feature: infrastructure
      payload:
        type: object
        required: [type, id, method, path]
        properties:
          type:
            enum: [proxy_request]
          id:
            type: string
            description: Correlation ID for matching response
          method:
            type: string
            description: HTTP method (GET, POST, PUT, DELETE)
          path:
            type: string
            description: Request path (e.g. /api/participant/register)
          body:
            type: string
            description: JSON-encoded request body (null for GET)
          headers:
            type: object
            additionalProperties:
              type: string
          participant_id:
            type: string
            description: UUID of the requesting participant (if applicable)

    # --- Daemon → Railway (publish) ---

    set_session_id:
      summary: Announce current session to Railway backend
      x-feature: session_management
      payload:
        type: object
        required: [type]
        properties:
          type:
            enum: [set_session_id]
          session_id:
            type: string
            description: Active session ID (null to clear)
          session_name:
            type: string
            description: Human-readable session name

    code_timestamp:
      summary: Daemon code version timestamp for cache busting
      x-feature: infrastructure
      payload:
        type: object
        required: [type, timestamp]
        properties:
          type:
            enum: [code_timestamp]
          timestamp:
            type: integer
            description: Unix timestamp of daemon code version

    broadcast:
      summary: Broadcast a typed event to all connected participants
      x-feature: infrastructure
      x-doc-notes:
        - "Wrapper message — inner event payload is a participant WS message (see Participant WS docs per feature)"
      payload:
        type: object
        required: [type, event]
        properties:
          type:
            enum: [broadcast]
          event:
            type: object
            description: Typed event payload (contains its own `type` discriminator)

    send_to_host:
      summary: Send a typed event to the host browser only
      x-feature: infrastructure
      x-doc-notes:
        - "Wrapper message — inner event payload is a host WS message (see Host WS docs per feature)"
      payload:
        type: object
        required: [type, event]
        properties:
          type:
            enum: [send_to_host]
          event:
            type: object
            description: Typed event payload (contains its own `type` discriminator)

    proxy_response:
      summary: Response to a proxy_request from Railway
      x-feature: infrastructure
      payload:
        type: object
        required: [type, id, status, body, content_type]
        properties:
          type:
            enum: [proxy_response]
          id:
            type: string
            description: Correlation ID matching the proxy_request
          status:
            type: integer
            description: HTTP status code
          body:
            type: string
            description: Response body (JSON-encoded)
          content_type:
            type: string

    daemon_ping:
      summary: Heartbeat ping from daemon to Railway
      x-feature: infrastructure
      payload:
        type: object
        required: [type]
        properties:
          type:
            enum: [daemon_ping]

    slide_invalidated:
      summary: Notify Railway that a cached slide is stale
      x-feature: slides
      payload:
        type: object
        required: [type, slug]
        properties:
          type:
            enum: [slide_invalidated]
          slug:
            type: string
            description: Slide slug to invalidate
```

- [ ] **Step 2: Add `infrastructure` feature to `docs/api-reference-features.md`**

Add this line to the feature list in `docs/api-reference-features.md`:

```
- `infrastructure` — Internal daemon↔railway transport plumbing (proxy, ping, session identity, code timestamp, broadcast/send_to_host wrappers)
```

- [ ] **Step 3: Commit**

```bash
git add docs/railway-ws.yaml docs/api-reference-features.md
git commit -m "docs: add AsyncAPI spec for daemon↔railway WS protocol"
```

---

### Task 2: Create `docs/railway-openapi.yaml` — OpenAPI Spec for Daemon ↔ Railway REST

**Files:**
- Create: `docs/railway-openapi.yaml`

- [ ] **Step 1: Create the OpenAPI spec file**

```yaml
# docs/railway-openapi.yaml
openapi: 3.1.0
info:
  title: Daemon ↔ Railway Internal REST API
  version: '1.0'
  description: |
    REST endpoints used between the daemon and Railway backend.
    All endpoints require Basic Auth (HOST_USERNAME / HOST_PASSWORD).
paths:
  /api/session/active:
    get:
      summary: Get active session ID
      x-feature: session_management
      description: Daemon calls on startup to discover if a session is already active on Railway.
      responses:
        '200':
          description: Active session info
          content:
            application/json:
              schema:
                type: object
                properties:
                  session_id:
                    type: string
                    description: Active session ID, or null if none
  /api/slides/download-from-gdrive/{slug}:
    post:
      summary: Download slide PDF from Google Drive
      x-feature: slides
      description: Daemon asks Railway to fetch a PDF export from Google Drive and cache it.
      parameters:
        - name: slug
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DownloadFromGdriveRequest'
      responses:
        '200':
          description: Download complete
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DownloadFromGdriveResponse'
  /upload/{file_id}:
    get:
      summary: Download uploaded file
      x-feature: paste_upload
      description: Daemon downloads a participant-uploaded file from Railway's temp storage.
      parameters:
        - name: file_id
          in: path
          required: true
          schema:
            type: integer
      responses:
        '200':
          description: File content (binary)
          content:
            application/octet-stream:
              schema:
                type: string
                format: binary
  /upload/{file_id}/ack:
    post:
      summary: Acknowledge file download
      x-feature: paste_upload
      description: Daemon confirms it has downloaded and saved the file. Railway deletes its temp copy.
      parameters:
        - name: file_id
          in: path
          required: true
          schema:
            type: integer
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/FileDownloadAck'
      responses:
        '200':
          description: Acknowledged

components:
  schemas:
    DownloadFromGdriveRequest:
      type: object
      required: [drive_export_url]
      properties:
        drive_export_url:
          type: string
          description: Google Drive export URL for the PDF
    DownloadFromGdriveResponse:
      type: object
      required: [size, sha256]
      properties:
        size:
          type: integer
          description: File size in bytes
        sha256:
          type: string
          description: SHA-256 hash of downloaded content
    FileDownloadAck:
      type: object
      required: [disk_path]
      properties:
        disk_path:
          type: string
          description: Local filesystem path where daemon saved the file
```

- [ ] **Step 2: Commit**

```bash
git add docs/railway-openapi.yaml
git commit -m "docs: add OpenAPI spec for daemon↔railway REST endpoints"
```

---

### Task 3: Add Contract Test for `railway-ws.yaml`

**Files:**
- Create: `tests/daemon/test_railway_ws_contract.py`

This test validates that `docs/railway-ws.yaml` matches the actual daemon WS handlers and Railway `push_to_daemon()` call sites.

- [ ] **Step 1: Write the contract test**

```python
# tests/daemon/test_railway_ws_contract.py
"""Contract tests: docs/railway-ws.yaml ↔ daemon WS handlers + Railway push_to_daemon calls."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RAILWAY_WS_YAML = ROOT / "docs" / "railway-ws.yaml"


def _load_spec() -> dict:
    return yaml.safe_load(RAILWAY_WS_YAML.read_text())


def _extract_channel_message_names(spec: dict, direction: str) -> set[str]:
    """Extract message names from subscribe (railway→daemon) or publish (daemon→railway)."""
    names: set[str] = set()
    for channel in spec.get("channels", {}).values():
        section = channel.get(direction, {})
        message = section.get("message", {})
        for ref in message.get("oneOf", []):
            ref_str = ref.get("$ref", "")
            if ref_str.startswith("#/components/messages/"):
                names.add(ref_str.split("/")[-1])
    return names


def _extract_daemon_handler_names() -> set[str]:
    """Parse daemon/__main__.py for ws_client.register_handler('msg_type', ...) calls."""
    main_py = ROOT / "daemon" / "__main__.py"
    source = main_py.read_text()
    names: set[str] = set()
    for match in re.finditer(r'register_handler\(\s*["\'](\w+)["\']', source):
        names.add(match.group(1))
    return names


def _extract_push_to_daemon_types() -> set[str]:
    """Scan railway/ for push_to_daemon({"type": ...}) calls to find outbound message types."""
    types: set[str] = set()
    railway_dir = ROOT / "railway"
    for py_file in railway_dir.rglob("*.py"):
        source = py_file.read_text()
        # Match push_to_daemon({"type": MSG_CONST or "literal", ...})
        for match in re.finditer(r'push_to_daemon\(\s*\{[^}]*"type"\s*:\s*(?:MSG_\w+|"(\w+)")', source):
            literal = match.group(1)
            if literal:
                types.add(literal)
    # Also resolve MSG_ constants from daemon_protocol.py
    protocol_file = ROOT / "railway" / "features" / "ws" / "daemon_protocol.py"
    constants: dict[str, str] = {}
    for match in re.finditer(r'(MSG_\w+)\s*=\s*"(\w+)"', protocol_file.read_text()):
        constants[match.group(1)] = match.group(2)
    # Re-scan for MSG_ references in push_to_daemon calls
    for py_file in railway_dir.rglob("*.py"):
        source = py_file.read_text()
        for match in re.finditer(r'push_to_daemon\(\s*\{[^}]*"type"\s*:\s*(MSG_\w+)', source):
            const_name = match.group(1)
            if const_name in constants:
                types.add(constants[const_name])
    return types


def _extract_message_fields(spec: dict, msg_name: str) -> set[str]:
    """Get payload field names for a message, excluding 'type' discriminator."""
    msg = spec.get("components", {}).get("messages", {}).get(msg_name, {})
    payload = msg.get("payload", {})
    props = payload.get("properties", {})
    return {k for k in props if k != "type"}


class TestRailwayWsSubscribe:
    """Railway → Daemon messages (subscribe channel)."""

    def test_subscribe_types_match_daemon_handlers(self):
        """Every subscribe message in YAML should have a daemon handler registered."""
        spec = _load_spec()
        yaml_names = _extract_channel_message_names(spec, "subscribe")
        handler_names = _extract_daemon_handler_names()
        missing = yaml_names - handler_names
        assert not missing, f"Messages in YAML with no daemon handler: {missing}"

    def test_daemon_handlers_are_documented(self):
        """Every daemon handler should be documented in YAML subscribe channel."""
        spec = _load_spec()
        yaml_names = _extract_channel_message_names(spec, "subscribe")
        handler_names = _extract_daemon_handler_names()
        # Some handlers may be for daemon-internal messages not in this spec
        # Only flag handlers that look like railway→daemon protocol messages
        protocol_file = ROOT / "railway" / "features" / "ws" / "daemon_protocol.py"
        protocol_types = set(re.findall(r'MSG_\w+\s*=\s*"(\w+)"', protocol_file.read_text()))
        undocumented = (handler_names & protocol_types) - yaml_names
        assert not undocumented, f"Daemon handlers for protocol messages not in YAML: {undocumented}"

    def test_all_subscribe_messages_have_x_feature(self):
        spec = _load_spec()
        yaml_names = _extract_channel_message_names(spec, "subscribe")
        messages = spec.get("components", {}).get("messages", {})
        missing = [n for n in yaml_names if not messages.get(n, {}).get("x-feature")]
        assert not missing, f"Subscribe messages without x-feature: {missing}"


class TestRailwayWsPublish:
    """Daemon → Railway messages (publish channel)."""

    def test_all_publish_messages_have_x_feature(self):
        spec = _load_spec()
        yaml_names = _extract_channel_message_names(spec, "publish")
        messages = spec.get("components", {}).get("messages", {})
        missing = [n for n in yaml_names if not messages.get(n, {}).get("x-feature")]
        assert not missing, f"Publish messages without x-feature: {missing}"

    def test_push_to_daemon_types_documented(self):
        """All message types sent via push_to_daemon() should appear in subscribe channel."""
        spec = _load_spec()
        yaml_subscribe = _extract_channel_message_names(spec, "subscribe")
        push_types = _extract_push_to_daemon_types()
        # Filter to types that are actual protocol messages (not broadcast/send_to_host)
        undocumented = push_types - yaml_subscribe
        # broadcast events are wrapped — they aren't direct subscribe messages
        assert not undocumented, f"push_to_daemon types not in YAML subscribe: {undocumented}"
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
cd /Users/victorrentea/workspace/training-assistant
python3 -m pytest tests/daemon/test_railway_ws_contract.py -v --confcutdir=tests/daemon
```

Expected: All tests PASS (the YAML was written to match the code).

- [ ] **Step 3: Fix any failures and re-run**

If any message names don't match, update `docs/railway-ws.yaml` to align with the actual code, then re-run.

- [ ] **Step 4: Commit**

```bash
git add tests/daemon/test_railway_ws_contract.py docs/railway-ws.yaml
git commit -m "test: add contract tests for railway WS spec"
```

---

### Task 4: Add Contract Test for `railway-openapi.yaml`

**Files:**
- Create: `tests/daemon/test_railway_api_contract.py` (or extend name to avoid clash — use `test_railway_rest_contract.py`)

This test validates that `docs/railway-openapi.yaml` paths and schemas match actual Railway FastAPI routes.

- [ ] **Step 1: Write the contract test**

```python
# tests/daemon/test_railway_rest_contract.py
"""Contract tests: docs/railway-openapi.yaml ↔ Railway FastAPI routes."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RAILWAY_OPENAPI_YAML = ROOT / "docs" / "railway-openapi.yaml"


def _load_spec() -> dict:
    return yaml.safe_load(RAILWAY_OPENAPI_YAML.read_text())


def _extract_spec_paths(spec: dict) -> dict[str, set[str]]:
    """Returns {path: {methods}} from the spec."""
    result: dict[str, set[str]] = {}
    for path, methods in spec.get("paths", {}).items():
        result[path] = {m.upper() for m in methods if m.lower() in {"get", "post", "put", "delete", "patch"}}
    return result


def _extract_railway_routes() -> dict[str, set[str]]:
    """Scan Railway router files for route decorators matching spec paths."""
    # We validate that declared paths exist in Railway source
    routes: dict[str, set[str]] = {}
    railway_dir = ROOT / "railway"
    for py_file in railway_dir.rglob("*.py"):
        source = py_file.read_text()
        for match in re.finditer(
            r'@\w+\.(get|post|put|delete|patch)\(\s*"([^"]+)"',
            source,
        ):
            method = match.group(1).upper()
            path = match.group(2)
            routes.setdefault(path, set()).add(method)
    # Also check daemon/http.py and daemon/upload.py for client-side calls
    return routes


def _extract_daemon_http_calls() -> list[tuple[str, str]]:
    """Find HTTP calls daemon makes to Railway (method, path pattern)."""
    calls: list[tuple[str, str]] = []
    daemon_dir = ROOT / "daemon"
    for py_file in daemon_dir.rglob("*.py"):
        source = py_file.read_text()
        # Look for URL patterns with /api/ or /upload/
        for match in re.finditer(r'["\'](?:GET|POST|PUT|DELETE)["\'].*?(/(?:api|upload)/[^\s"\']+)', source):
            calls.append(("?", match.group(1)))
    return calls


class TestRailwayOpenApi:

    def test_all_operations_have_x_feature(self):
        spec = _load_spec()
        missing = []
        for path, methods in spec.get("paths", {}).items():
            for method, op in methods.items():
                if method.lower() not in {"get", "post", "put", "delete", "patch"}:
                    continue
                if not isinstance(op, dict):
                    continue
                if not op.get("x-feature"):
                    missing.append(f"{method.upper()} {path}")
        assert not missing, f"Operations without x-feature: {missing}"

    def test_spec_paths_exist_in_railway_or_daemon(self):
        """Every path in the spec should correspond to a Railway route or daemon HTTP call."""
        spec = _load_spec()
        spec_paths = set(spec.get("paths", {}).keys())
        railway_routes = _extract_railway_routes()
        # Normalize path params: /upload/{file_id} should match /upload/{file_id}
        railway_paths = set(railway_routes.keys())
        # Some paths use different param syntax — check normalized
        for spec_path in spec_paths:
            normalized = re.sub(r'\{[^}]+\}', '{param}', spec_path)
            matches = [rp for rp in railway_paths if re.sub(r'\{[^}]+\}', '{param}', rp) == normalized]
            assert matches, f"Spec path {spec_path} not found in Railway routes"
```

- [ ] **Step 2: Run the test**

```bash
python3 -m pytest tests/daemon/test_railway_rest_contract.py -v --confcutdir=tests/daemon
```

- [ ] **Step 3: Fix any failures and re-run**

- [ ] **Step 4: Commit**

```bash
git add tests/daemon/test_railway_rest_contract.py
git commit -m "test: add contract tests for railway REST spec"
```

---

### Task 5: Extend `FeatureSection` and Generator to Support Daemon Audience

**Files:**
- Modify: `scripts/generate_apis_md.py` (lines 32-56, 99-104, 937-991, 994-1047)

- [ ] **Step 1: Add `infrastructure` to FEATURE_LABELS and FEATURE_ORDER**

In `scripts/generate_apis_md.py`, add to `FEATURE_LABELS` dict (around line 53):

```python
    "infrastructure": "Infrastructure",
```

Add to `FEATURE_ORDER` list (around line 76, before `"misc"`):

```python
    "infrastructure",
```

- [ ] **Step 2: Extend `FeatureSection` dataclass with daemon fields**

Change the `FeatureSection` dataclass (lines 99-104) to:

```python
@dataclass
class FeatureSection:
    participant_rest: list[RestOp]
    participant_ws: list[WsMsg]
    host_rest: list[RestOp]
    host_ws: list[WsMsg]
    daemon_rest: list[RestOp]
    daemon_ws: list[WsMsg]
```

Update the `sections.setdefault(...)` calls in `_extract_rest` (line 622) and `_extract_ws` (line 667) to include the two new empty lists:

```python
section = sections.setdefault(feature, FeatureSection([], [], [], [], [], []))
```

- [ ] **Step 3: Add `_extract_rest` support for daemon audience**

Add a new function `_extract_railway_rest` that loads the railway OpenAPI spec and populates `daemon_rest` lists. Place it after the existing `_extract_rest` function (after line 638):

```python
def _extract_railway_rest(openapi: dict[str, Any], sections: dict[str, FeatureSection]) -> None:
    for path, methods in sorted(openapi.get("paths", {}).items()):
        if not isinstance(methods, dict):
            continue
        for method, op in sorted(methods.items()):
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(op, dict):
                continue

            feature = str(op.get("x-feature") or "infrastructure")
            section = sections.setdefault(feature, FeatureSection([], [], [], [], [], []))

            title, notes = _collect_rest_doc(op)
            rest = RestOp(
                method=method.upper(),
                path=path,
                title=title,
                notes=notes,
                request_shape=_rest_request_shape(op, openapi),
                response_shape=_rest_response_shape(op, openapi),
            )
            section.daemon_rest.append(rest)
```

- [ ] **Step 4: Add `_extract_ws` support for daemon audience (both directions)**

The railway WS spec has both `subscribe` and `publish` channels. Add a new extraction function after `_extract_ws` (after line 677):

```python
def _extract_railway_ws(
    spec: dict[str, Any],
    sections: dict[str, FeatureSection],
) -> None:
    components = spec.get("components", {})
    messages = components.get("messages", {})

    for channel in spec.get("channels", {}).values():
        if not isinstance(channel, dict):
            continue
        for direction in ("subscribe", "publish"):
            dir_spec = channel.get(direction, {})
            message = dir_spec.get("message", {})
            one_of = message.get("oneOf", [])
            for ref in one_of:
                if not isinstance(ref, dict):
                    continue
                ref_str = str(ref.get("$ref", ""))
                if not ref_str.startswith("#/components/messages/"):
                    continue
                msg_name = ref_str.split("/")[-1]
                msg_spec = messages.get(msg_name, {})
                if not isinstance(msg_spec, dict):
                    continue

                feature = str(msg_spec.get("x-feature") or "infrastructure")
                section = sections.setdefault(feature, FeatureSection([], [], [], [], [], []))
                payload = msg_spec.get("payload", {})
                direction_label = "→daemon" if direction == "subscribe" else "daemon→"
                ws = WsMsg(
                    name=msg_name,
                    notes=[f"Direction: {direction_label}"] + _collect_notes(msg_spec),
                    payload_shape=_ws_payload_shape(payload if isinstance(payload, dict) else {}, spec),
                )
                section.daemon_ws.append(ws)
```

- [ ] **Step 5: Update `generate_api_reference` to accept and use new specs**

Modify the `generate_api_reference` function signature and body (lines 937-991):

```python
def generate_api_reference(
    openapi_path: Path,
    participant_ws_path: Path,
    host_ws_path: Path,
    railway_openapi_path: Path | None = None,
    railway_ws_path: Path | None = None,
) -> str:
    openapi = _load_yaml(openapi_path)
    participant_ws = _load_yaml(participant_ws_path)
    host_ws = _load_yaml(host_ws_path)

    sections: dict[str, FeatureSection] = {}

    _extract_rest(openapi, sections)
    _extract_ws(participant_ws, sections, "participant")
    _extract_ws(host_ws, sections, "host")

    railway_openapi = None
    if railway_openapi_path and railway_openapi_path.exists():
        railway_openapi = _load_yaml(railway_openapi_path)
        _extract_railway_rest(railway_openapi, sections)

    railway_ws = None
    if railway_ws_path and railway_ws_path.exists():
        railway_ws = _load_yaml(railway_ws_path)
        _extract_railway_ws(railway_ws, sections)

    feature_ids = [f for f in FEATURE_ORDER if f in sections]
    feature_ids.extend(sorted(f for f in sections.keys() if f not in feature_ids))

    source_files = "`docs/openapi.yaml`, `docs/participant-ws.yaml`, `docs/host-ws.yaml`"
    if railway_openapi_path:
        source_files += ", `docs/railway-openapi.yaml`"
    if railway_ws_path:
        source_files += ", `docs/railway-ws.yaml`"

    lines: list[str] = []
    lines.append("# API Reference (Generated from Contracts)")
    lines.append("")
    lines.append(f"Generated from {source_files}.")
    lines.append("")

    lines.append("## Table of Contents")
    for feature_id in feature_ids:
        title = _feature_title(feature_id)
        anchor = "feature-" + title.lower().replace("&", "").replace(":", "").replace(" ", "-")
        lines.append(f"- [{title}](#{anchor})")
    lines.append("")

    for feature_id in feature_ids:
        title = _feature_title(feature_id)
        section = sections[feature_id]
        subsections: list[tuple[str, list[str]]] = []
        if section.participant_rest:
            subsections.append(("Participant REST", _render_rest(section.participant_rest, openapi)))
        if section.participant_ws:
            subsections.append(("Participant WS", _render_ws(section.participant_ws, participant_ws)))
        if section.host_rest:
            subsections.append(("Host REST", _render_rest(section.host_rest, openapi)))
        if section.host_ws:
            subsections.append(("Host WS", _render_ws(section.host_ws, host_ws)))
        if section.daemon_rest and railway_openapi:
            subsections.append(("Daemon REST", _render_rest(section.daemon_rest, railway_openapi)))
        if section.daemon_ws and railway_ws:
            subsections.append(("Daemon WS", _render_ws(section.daemon_ws, railway_ws)))

        if not subsections:
            continue

        lines.append(f"## Feature: {title}")
        lines.append("")
        for subsection_title, subsection_lines in subsections:
            lines.append(f"### {subsection_title}")
            lines.extend(subsection_lines)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 6: Update CLI args in `main()`**

Add the two new CLI arguments (around line 998):

```python
    parser.add_argument("--railway-openapi", default="docs/railway-openapi.yaml")
    parser.add_argument("--railway-ws", default="docs/railway-ws.yaml")
```

Update the `generate_api_reference` call (around line 1004):

```python
    content = generate_api_reference(
        Path(args.openapi),
        Path(args.participant_ws),
        Path(args.host_ws),
        railway_openapi_path=Path(args.railway_openapi),
        railway_ws_path=Path(args.railway_ws),
    )
```

- [ ] **Step 7: Run the generator and verify output**

```bash
python3 scripts/generate_apis_md.py --output API.md
```

Verify API.md now contains "Daemon REST" and "Daemon WS" subsections under relevant features, and an "Infrastructure" feature section.

- [ ] **Step 8: Commit**

```bash
git add scripts/generate_apis_md.py API.md
git commit -m "feat: extend API generator to include daemon↔railway specs"
```

---

### Task 6: Update Pre-commit Hook and CI

**Files:**
- Modify: any pre-commit or CI config that runs the generator (check `.pre-commit-config.yaml`, `hooks/`, or CI files)

- [ ] **Step 1: Find where the generator is invoked in hooks/CI**

Search for `generate_apis_md` in hooks and CI configuration files. The generator already auto-runs — verify it picks up the new `--railway-openapi` and `--railway-ws` args via defaults.

- [ ] **Step 2: Verify the pre-commit hook still passes**

```bash
python3 scripts/generate_apis_md.py --output API.md
git diff API.md  # should show no diff if already regenerated
```

- [ ] **Step 3: Run full test suite**

```bash
bash tests/check-all.sh
```

- [ ] **Step 4: Commit any remaining changes**

```bash
git add -A
git commit -m "chore: update hooks/CI for railway API specs"
```

---

### Task 7: Final Verification and Push

**Files:** None (verification only)

- [ ] **Step 1: Run all daemon contract tests**

```bash
python3 -m pytest tests/daemon/test_railway_ws_contract.py tests/daemon/test_railway_rest_contract.py tests/daemon/test_ws_contract.py tests/daemon/test_api_contract.py -v --confcutdir=tests/daemon
```

- [ ] **Step 2: Regenerate API.md and verify**

```bash
python3 scripts/generate_apis_md.py --output API.md
```

Inspect API.md to confirm:
- "Infrastructure" feature section exists with Daemon WS subsection
- "Slides" feature has Daemon REST + Daemon WS subsections
- "Identity" feature has Daemon WS subsection
- "Paste & File Upload" has Daemon REST + Daemon WS subsections
- "Notes & Summary" has Daemon WS subsection
- "Scores & Leaderboard" has Daemon WS subsection
- "Session" has Daemon REST + Daemon WS subsections

- [ ] **Step 3: Run full check-all**

```bash
bash tests/check-all.sh
```

- [ ] **Step 4: Push to master**

```bash
git push origin master
```
