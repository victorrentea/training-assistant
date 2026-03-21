# Production Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Prometheus metrics from the workshop app and provide a local Docker Compose stack (Grafana + Prometheus) for live workshop observability demos.

**Architecture:** `prometheus-fastapi-instrumentator` auto-instruments HTTP endpoints. Custom metrics (WebSocket connections, votes, Q&A) are defined in a standalone `metrics.py` module and incremented at existing handler sites. A `monitoring/` directory contains Docker Compose with pre-provisioned Grafana dashboards scraping production.

**Tech Stack:** Python 3.12, FastAPI, prometheus-fastapi-instrumentator, prometheus-client, Docker Compose, Grafana, Prometheus

**Spec:** `docs/superpowers/specs/2026-03-21-prod-metrics-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `metrics.py` | All custom Prometheus metric definitions + helpers |
| Modify | `main.py` | Attach instrumentator, expose `/metrics` with auth |
| Modify | `routers/ws.py` | Increment custom metrics at handler sites |
| Modify | `pyproject.toml` | Add `prometheus-fastapi-instrumentator` dependency |
| Create | `test_metrics.py` | Tests for `/metrics` endpoint and custom metric increments |
| Create | `monitoring/docker-compose.yml` | Grafana + Prometheus containers |
| Create | `monitoring/prometheus.yml.tmpl` | Prometheus scrape config template |
| Create | `monitoring/start.sh` | Startup script reading secrets.env |
| Create | `monitoring/grafana/provisioning/datasources/prometheus.yml` | Auto-configure Prometheus datasource |
| Create | `monitoring/grafana/provisioning/dashboards/dashboards.yml` | Dashboard provider config |
| Create | `monitoring/grafana/provisioning/dashboards/workshop.json` | Pre-built Grafana dashboard |

---

### Task 1: Add dependency and create metrics.py

**Files:**
- Modify: `pyproject.toml:6-11` (add dependency)
- Create: `metrics.py`

- [ ] **Step 1: Add prometheus-fastapi-instrumentator to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list:

```toml
"prometheus-fastapi-instrumentator>=7.0.0",
```

- [ ] **Step 2: Create metrics.py with all custom metric definitions**

```python
"""Prometheus custom metrics for the Workshop Tool."""

from prometheus_client import Counter, Gauge, Histogram

# WebSocket connections (host, overlay, participant)
ws_connections_active = Gauge(
    "ws_connections_active",
    "Currently open WebSocket connections",
    ["role"],
)

# All WebSocket messages by type
ws_messages_total = Counter(
    "ws_messages_total",
    "Total WebSocket messages received",
    ["type"],
)

# Poll voting
poll_votes_total = Counter(
    "poll_votes_total",
    "Total votes cast",
)

poll_vote_duration_seconds = Histogram(
    "poll_vote_duration_seconds",
    "Time from poll open to participant vote",
    buckets=[1, 2, 5, 10, 15, 30, 60, 120, 300],
)

# Q&A
qa_questions_total = Counter(
    "qa_questions_total",
    "Total Q&A questions submitted",
)

qa_upvotes_total = Counter(
    "qa_upvotes_total",
    "Total Q&A upvotes given",
)
```

- [ ] **Step 3: Install dependency locally**

Run: `pip3 install prometheus-fastapi-instrumentator>=7.0.0`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml metrics.py
git commit -m "feat: add Prometheus metrics definitions and dependency"
```

---

### Task 2: Wire instrumentator into main.py and expose /metrics

**Files:**
- Modify: `main.py:1-32`

- [ ] **Step 1: Write test for /metrics endpoint**

Create `test_metrics.py`:

```python
"""Tests for Prometheus metrics endpoint."""

import base64
import json
import os
import pytest
from fastapi.testclient import TestClient

from main import app, state
import auth  # noqa: ensure secrets.env is loaded

_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


def test_metrics_endpoint_requires_auth():
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 401


def test_metrics_endpoint_returns_prometheus_format():
    client = TestClient(app)
    resp = client.get("/metrics", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.text
    # Auto-instrumented metrics should be present
    assert "http_request" in body
    # Custom metrics should be present
    assert "ws_connections_active" in body
    assert "poll_votes_total" in body
    assert "qa_questions_total" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_metrics.py -v`
Expected: FAIL (no `/metrics` route yet)

- [ ] **Step 3: Wire instrumentator in main.py**

After `app = FastAPI(title="Workshop Tool")` (line 17), before router includes, add:

```python
from prometheus_fastapi_instrumentator import Instrumentator
from auth import require_host_auth

Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", dependencies=[Depends(require_host_auth)]
)
```

Note: `require_host_auth` is already imported on line 11. The full modified `main.py` imports section becomes:

```python
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from auth import require_host_auth
from state import state
from routers import ws, poll, scores, quiz, pages, wordcloud, activity, qa, codereview, summary, debate
```

And after `app = FastAPI(...)`:

```python
Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", dependencies=[Depends(require_host_auth)]
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `python3 -m pytest test_main.py -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add main.py test_metrics.py
git commit -m "feat: expose /metrics endpoint with Prometheus auto-instrumentation"
```

---

### Task 3: Instrument WebSocket handlers with custom metrics

**Files:**
- Modify: `routers/ws.py:1-312`

- [ ] **Step 1: Write tests for custom metric increments**

Append to `test_metrics.py`:

```python
from prometheus_client import REGISTRY


def _get_metric_value(name, labels=None):
    """Get current value of a Prometheus metric."""
    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                if labels is None or all(sample.labels.get(k) == v for k, v in labels.items()):
                    return sample.value
    return None


def test_ws_connection_increments_gauge():
    """WebSocket connect should increment ws_connections_active."""
    client = TestClient(app)
    before = _get_metric_value("ws_connections_active", {"role": "participant"}) or 0
    with client.websocket_connect("/ws/test-metrics-participant") as ws:
        ws.send_text(json.dumps({"type": "set_name", "name": "MetricsTest"}))
        # Drain initial state message
        for _ in range(5):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "state":
                break
        during = _get_metric_value("ws_connections_active", {"role": "participant"})
        assert during is not None
        assert during > before
    # After disconnect, gauge should go back
    after = _get_metric_value("ws_connections_active", {"role": "participant"})
    assert after == before


def test_vote_increments_counter():
    """Voting should increment poll_votes_total."""
    client = TestClient(app)
    before = _get_metric_value("poll_votes_total", {}) or 0

    # Create and open a poll via host API
    client.post("/api/poll", json={
        "question": "Metrics test?",
        "options": [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}],
    }, headers=_HOST_AUTH_HEADERS)
    client.post("/api/poll/status", json={"active": True}, headers=_HOST_AUTH_HEADERS)

    with client.websocket_connect("/ws/test-metrics-voter") as ws:
        ws.send_text(json.dumps({"type": "set_name", "name": "Voter"}))
        for _ in range(5):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "state":
                break
        ws.send_text(json.dumps({"type": "vote", "option_id": "a"}))
        # Drain vote_update
        for _ in range(5):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "vote_update":
                break

    after = _get_metric_value("poll_votes_total", {})
    assert after is not None
    assert after > before

    # Cleanup
    state.poll = None
    state.poll_active = False
    state.poll_opened_at = None
    state.poll_correct_ids = None
    state.votes.clear()
    state.vote_times.clear()


def test_ws_messages_tracked_by_type():
    """Every WS message should increment ws_messages_total with type label."""
    client = TestClient(app)
    before = _get_metric_value("ws_messages_total", {"type": "set_name"}) or 0
    with client.websocket_connect("/ws/test-metrics-msg") as ws:
        ws.send_text(json.dumps({"type": "set_name", "name": "MsgTest"}))
        for _ in range(5):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "state":
                break
    after = _get_metric_value("ws_messages_total", {"type": "set_name"})
    assert after is not None
    assert after > before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test_metrics.py::test_ws_connection_increments_gauge test_metrics.py::test_vote_increments_counter test_metrics.py::test_ws_messages_tracked_by_type -v`
Expected: FAIL (metrics not incremented yet)

- [ ] **Step 3: Add metric imports and instrumentation to routers/ws.py**

At the top of `routers/ws.py`, add import:

```python
from metrics import (
    ws_connections_active,
    ws_messages_total,
    poll_votes_total,
    poll_vote_duration_seconds,
    qa_questions_total,
    qa_upvotes_total,
)
```

**Right after** `is_overlay = pid == "__overlay__"` (line 33), define the role variable early to ensure it's available in the disconnect handler:

```python
    role = "host" if is_host else ("overlay" if is_overlay else "participant")
```

**After** `state.participants[pid] = websocket` (line 56), add connection tracking:

```python
    ws_connections_active.labels(role=role).inc()
```

**At the top of the message loop** (after `msg_type = data.get("type")`, line 77), add message tracking:

```python
            if msg_type:
                ws_messages_total.labels(type=msg_type).inc()
```

**In the `vote` handler** (after `state.vote_times[pid] = datetime.now(timezone.utc)`, line 133), add:

```python
                        poll_votes_total.inc()
                        if state.poll_opened_at:
                            duration = (datetime.now(timezone.utc) - state.poll_opened_at).total_seconds()
                            poll_vote_duration_seconds.observe(duration)
```

**In the `multi_vote` handler** (after `state.vote_times[pid] = datetime.now(timezone.utc)`, line 156), add:

```python
                        poll_votes_total.inc()
                        if state.poll_opened_at:
                            duration = (datetime.now(timezone.utc) - state.poll_opened_at).total_seconds()
                            poll_vote_duration_seconds.observe(duration)
```

**In the `qa_submit` handler** (after `state.scores[pid] = ...`, line 183), add:

```python
                    qa_questions_total.inc()
```

**In the `qa_upvote` handler** (after both score updates on lines 192-193, before `await broadcast_state()` on line 194), add:

```python
                    qa_upvotes_total.inc()
```

**In the `except WebSocketDisconnect` block** (after `state.participants.pop(pid, None)`, line 307), add:

```python
        ws_connections_active.labels(role=role).dec()
```

Note: `role` is defined early (right after `is_host`/`is_overlay` on line 33), so it's always available in the disconnect handler.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test_metrics.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest test_main.py test_metrics.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add routers/ws.py test_metrics.py
git commit -m "feat: instrument WebSocket handlers with custom Prometheus metrics"
```

---

### Task 4: Create monitoring Docker Compose stack

**Files:**
- Create: `monitoring/docker-compose.yml`
- Create: `monitoring/prometheus.yml.tmpl`
- Create: `monitoring/start.sh`
- Create: `monitoring/grafana/provisioning/datasources/prometheus.yml`
- Create: `monitoring/grafana/provisioning/dashboards/dashboards.yml`

- [ ] **Step 1: Create monitoring/docker-compose.yml**

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    entrypoint: ["/bin/sh", "-c"]
    command:
      - "envsubst < /etc/prometheus/prometheus.yml.tmpl > /tmp/prometheus.yml && /bin/prometheus --config.file=/tmp/prometheus.yml --web.listen-address=:9090"
    environment:
      - HOST_USERNAME=${HOST_USERNAME}
      - HOST_PASSWORD=${HOST_PASSWORD}
    volumes:
      - ./prometheus.yml.tmpl:/etc/prometheus/prometheus.yml.tmpl:ro
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
```

- [ ] **Step 2: Create monitoring/prometheus.yml.tmpl**

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "workshop"
    scheme: https
    metrics_path: /metrics
    basic_auth:
      username: "${HOST_USERNAME}"
      password: "${HOST_PASSWORD}"
    static_configs:
      - targets: ["interact.victorrentea.ro"]
```

- [ ] **Step 3: Create monitoring/start.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_FILE="$SCRIPT_DIR/../secrets.env"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "Error: $SECRETS_FILE not found. Create it with HOST_USERNAME and HOST_PASSWORD."
    exit 1
fi

# Load secrets
set -a
source "$SECRETS_FILE"
set +a

cd "$SCRIPT_DIR"
docker compose up -d

echo ""
echo "Grafana:    http://localhost:3000  (no login required)"
echo "Prometheus: http://localhost:9090"
```

Make executable: `chmod +x monitoring/start.sh`

- [ ] **Step 4: Create monitoring/grafana/provisioning/datasources/prometheus.yml**

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

- [ ] **Step 5: Create monitoring/grafana/provisioning/dashboards/dashboards.yml**

```yaml
apiVersion: 1

providers:
  - name: "default"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: false
```

- [ ] **Step 6: Commit**

```bash
git add monitoring/
git commit -m "feat: add Docker Compose monitoring stack (Grafana + Prometheus)"
```

---

### Task 5: Create pre-configured Grafana dashboard

**Files:**
- Create: `monitoring/grafana/provisioning/dashboards/workshop.json`

- [ ] **Step 1: Create the dashboard JSON**

Create `monitoring/grafana/provisioning/dashboards/workshop.json` with a Grafana dashboard containing these panels:

1. **Request Latency (p50/p95/p99)** — timeseries panel
   - Query: `histogram_quantile(0.5, rate(http_request_duration_seconds_bucket[1m]))` (repeat for 0.95, 0.99)
2. **Active WebSocket Connections** — stat panel
   - Query: `sum(ws_connections_active)`
   - Also: `ws_connections_active` by role (timeseries)
3. **Votes per Minute** — timeseries panel
   - Query: `rate(poll_votes_total[1m]) * 60`
4. **Error Rate** — timeseries panel
   - Query: `sum(rate(http_requests_total{status=~"4..|5.."}[1m]))`
5. **Q&A Activity** — stat panels
   - Queries: `qa_questions_total`, `qa_upvotes_total`
6. **WebSocket Messages by Type** — timeseries panel
   - Query: `rate(ws_messages_total[1m])` grouped by `type`
7. **Vote Duration Distribution** — heatmap or histogram panel
   - Query: `rate(poll_vote_duration_seconds_bucket[5m])`

The dashboard JSON should use Grafana's standard export format. Title: "Workshop Live Metrics". Auto-refresh: 5s.

- [ ] **Step 2: Commit**

```bash
git add monitoring/grafana/provisioning/dashboards/workshop.json
git commit -m "feat: add pre-configured Grafana dashboard for workshop metrics"
```

---

### Task 6: Add monitoring/ to .gitignore for runtime files and update docs

**Files:**
- Modify: `.gitignore` (if exists, else create)

- [ ] **Step 1: Check if .gitignore exists and update**

Add to `.gitignore` (do not gitignore the monitoring config files themselves, only Docker runtime data):

```
# Monitoring runtime data
monitoring/data/
```

- [ ] **Step 2: Verify the full stack works locally**

Run: `python3 -m pytest test_metrics.py test_main.py -v`
Expected: All tests PASS

- [ ] **Step 3: Final commit**

```bash
git add .gitignore
git commit -m "chore: gitignore monitoring runtime data"
```

---

## Verification Checklist

After all tasks:

1. `python3 -m pytest test_metrics.py test_main.py -v` — all tests pass
2. `curl -u host:host http://localhost:8000/metrics` — returns Prometheus format with both auto and custom metrics
3. `curl http://localhost:8000/metrics` — returns 401
4. `cd monitoring && ./start.sh` — Grafana at localhost:3000 shows dashboard with panels (data appears once deployed to production)
