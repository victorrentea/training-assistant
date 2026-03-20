# Production Metrics -- Design Spec

**Date:** 2026-03-21
**Goal:** Expose Prometheus metrics from the workshop interaction tool and visualize them in a local Grafana during live workshops.

**Use case:** During workshops, the trainer demonstrates production observability by showing a local Grafana dashboard pulling real metrics from the live application at `interact.victorrentea.ro`.

---

## 1. Backend -- `/metrics` Endpoint

### Auto-instrumented HTTP metrics

Library: `prometheus_fastapi_instrumentator`

Provides out of the box:
- `http_request_duration_seconds` (Histogram) -- per method, path, status code. Enables p50/p95/p99 latency queries.
- `http_requests_total` (Counter) -- per method, path, status code. Enables request rate and error rate.
- `http_requests_inprogress` (Gauge) -- in-flight requests.

### Custom metrics

Library: `prometheus_client` (pulled in as dependency of the instrumentator)

Defined in a new module `metrics.py`:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `ws_connections_active` | Gauge | -- | Currently open WebSocket connections |
| `ws_messages_total` | Counter | `type` | WebSocket messages received (vote, qa_submit, upvote, set_name, etc.) |
| `poll_votes_total` | Counter | -- | Total votes cast |
| `poll_vote_duration_seconds` | Histogram | -- | Time from poll open to participant vote |
| `activity_participants_total` | Counter | `activity_type` | Participants per activity type (poll, qa, wordcloud, codereview) |
| `qa_questions_total` | Counter | -- | Questions submitted |
| `qa_upvotes_total` | Counter | -- | Upvotes given |

### Endpoint security

`GET /metrics` is protected by HTTP Basic Auth using the same credentials as `/host` (from `secrets.env`).

### Integration points

Each existing handler gets 1-2 lines added:
- WebSocket connect/disconnect: `ws_connections_active.inc()` / `.dec()`
- Vote handler: `poll_votes_total.inc()` + `poll_vote_duration_seconds.observe(duration)`
- Q&A submit handler: `qa_questions_total.inc()`
- Upvote handler: `qa_upvotes_total.inc()`
- Every WS message: `ws_messages_total.labels(type=msg_type).inc()`
- Code review selection: `activity_participants_total.labels(activity_type="codereview").inc()`

### Dependencies

Add to `pyproject.toml`:
- `prometheus-fastapi-instrumentator`
- `prometheus-client`

---

## 2. Docker Compose -- Local Grafana + Prometheus

### File structure

```
monitoring/
├── docker-compose.yml
├── prometheus.yml
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── prometheus.yml
        └── dashboards/
            ├── dashboards.yml
            └── workshop.json
```

### Prometheus

- Scrapes `https://interact.victorrentea.ro/metrics` every 15 seconds
- Basic Auth credentials passed via environment variables at `docker compose up`

### Grafana

- Runs on `localhost:3000`
- Prometheus auto-configured as datasource via provisioning
- Pre-configured dashboard "Workshop Live Metrics" with panels:
  - **Request Latency** -- p50/p95/p99 from `http_request_duration_seconds`
  - **Active WebSocket Connections** -- `ws_connections_active`
  - **Votes per Minute** -- `rate(poll_votes_total[1m])`
  - **Error Rate** -- `rate(http_requests_total{status=~"4..|5.."}[1m])`
  - **Participation** -- questions, upvotes, poll completion counters

### Startup

```bash
cd monitoring
HOST_USERNAME=xxx HOST_PASSWORD=xxx docker compose up -d
```

Then open `http://localhost:3000` (default Grafana credentials: admin/admin).

---

## 3. Architecture Decisions

- **No new infrastructure on Railway** -- Prometheus and Grafana run locally only. The production app just exposes `/metrics`.
- **Same Basic Auth** -- reuses existing host credentials, no new auth mechanism.
- **Separate `metrics.py` module** -- keeps metric definitions out of `main.py`, clean imports from routers.
- **Minimal handler changes** -- 1-2 lines per handler, no logic changes.
- **Provisioned dashboards** -- `docker compose up` gives a ready-to-use Grafana, no manual setup during workshops.
