# Production Metrics -- Design Spec

**Date:** 2026-03-21
**Goal:** Expose Prometheus metrics from the workshop interaction tool and visualize them in a local Grafana during live workshops.

**Use case:** During workshops, the trainer demonstrates production observability by showing a local Grafana dashboard pulling real metrics from the live application at `interact.victorrentea.ro`.

---

## 1. Backend -- `/metrics` Endpoint

### Auto-instrumented HTTP metrics

Library: `prometheus-fastapi-instrumentator>=7.0.0`

Provides out of the box:
- `http_request_duration_seconds` (Histogram) -- per method, path, status code. Enables p50/p95/p99 latency queries.
- `http_requests_total` (Counter) -- per method, path, status code. Enables request rate and error rate.
- `http_requests_inprogress` (Gauge) -- in-flight requests.

### Custom metrics

Library: `prometheus_client` (pulled in transitively by the instrumentator)

Defined in a new module `metrics.py`:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `ws_connections_active` | Gauge | `role` | Currently open WebSocket connections (labels: `participant`, `host`, `overlay`) |
| `ws_messages_total` | Counter | `type` | All WebSocket messages received (vote, multi_vote, qa_submit, upvote, set_name, wordcloud_word, debate_pick_side, debate_argument, debate_upvote, codereview_select, codereview_deselect, emoji_reaction, etc.) |
| `poll_votes_total` | Counter | -- | Total votes cast (incremented in both `vote` and `multi_vote` handlers) |
| `poll_vote_duration_seconds` | Histogram | -- | Time from poll open to participant vote. Duration = `datetime.now(utc) - state.poll_opened_at`; only observe when `poll_opened_at` is set. |
| `qa_questions_total` | Counter | -- | Questions submitted |
| `qa_upvotes_total` | Counter | -- | Upvotes given |

Note: `activity_participants_total` was removed -- it would be redundant with the per-activity counters above and the `ws_messages_total` counter which already tracks all message types.

### Endpoint registration

```python
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator()
instrumentator.instrument(app)
instrumentator.expose(app, endpoint="/metrics", dependencies=[Depends(require_host_auth)])
```

The `Instrumentator().instrument(app)` call must happen after `app = FastAPI(...)` and before the server starts.

### Integration points

Each existing handler gets 1-2 lines added:
- WebSocket connect/disconnect: `ws_connections_active.labels(role=role).inc()` / `.dec()` (role determined from uuid: `__host__`, `__overlay__`, or `participant`)
- Vote handler (`vote` + `multi_vote`): `poll_votes_total.inc()` + `poll_vote_duration_seconds.observe(duration)`
- Q&A submit handler: `qa_questions_total.inc()`
- Upvote handler: `qa_upvotes_total.inc()`
- Every WS message: `ws_messages_total.labels(type=msg_type).inc()`

### Dependencies

Add to `pyproject.toml`:
- `prometheus-fastapi-instrumentator>=7.0.0`

(`prometheus-client` is pulled in transitively)

---

## 2. Docker Compose -- Local Grafana + Prometheus

### File structure

```
monitoring/
├── docker-compose.yml
├── prometheus.yml.tmpl        ← Template with ${HOST_USERNAME} / ${HOST_PASSWORD} placeholders
├── start.sh                   ← Reads secrets.env, runs envsubst, then docker compose up
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── prometheus.yml
        └── dashboards/
            ├── dashboards.yml
            └── workshop.json
```

### Prometheus credential injection

Prometheus does not support environment variable substitution in its config file natively. Solution:

1. `prometheus.yml.tmpl` contains `${HOST_USERNAME}` and `${HOST_PASSWORD}` placeholders in the `basic_auth` section
2. The Prometheus container's entrypoint in `docker-compose.yml` runs `envsubst` to render the template before starting Prometheus:
   ```yaml
   prometheus:
     image: prom/prometheus
     entrypoint: ["/bin/sh", "-c"]
     command:
       - "envsubst < /etc/prometheus/prometheus.yml.tmpl > /etc/prometheus/prometheus.yml && /bin/prometheus --config.file=/etc/prometheus/prometheus.yml"
     environment:
       - HOST_USERNAME=${HOST_USERNAME}
       - HOST_PASSWORD=${HOST_PASSWORD}
   ```

### Prometheus scrape config (template)

- Scrapes `https://interact.victorrentea.ro/metrics` every 15 seconds
- Uses `basic_auth` with credentials injected via `envsubst`

### Grafana

- Runs on `localhost:3000`
- Anonymous access enabled with Admin role (`GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`) -- no login prompt during demos
- Prometheus auto-configured as datasource via provisioning
- Pre-configured dashboard "Workshop Live Metrics" with panels:
  - **Request Latency** -- p50/p95/p99 from `http_request_duration_seconds`
  - **Active WebSocket Connections** -- `ws_connections_active` (with role breakdown)
  - **Votes per Minute** -- `rate(poll_votes_total[1m])`
  - **Error Rate** -- `rate(http_requests_total{status=~"4..|5.."}[1m])`
  - **Participation** -- questions, upvotes counters
  - **WebSocket Message Rate** -- `rate(ws_messages_total[1m])` by type

### Startup

```bash
cd monitoring && ./start.sh
```

`start.sh` reads `HOST_USERNAME` and `HOST_PASSWORD` from `../secrets.env` and exports them before running `docker compose up -d`.

Then open `http://localhost:3000` (no login required).

---

## 3. Architecture Decisions

- **No new infrastructure on Railway** -- Prometheus and Grafana run locally only. The production app just exposes `/metrics`.
- **Same Basic Auth** -- reuses existing host credentials, no new auth mechanism.
- **Separate `metrics.py` module** -- keeps metric definitions out of `main.py`, clean imports from routers.
- **Minimal handler changes** -- 1-2 lines per handler, no logic changes.
- **Provisioned dashboards** -- `docker compose up` gives a ready-to-use Grafana, no manual setup during workshops.
- **Anonymous Grafana access** -- avoids password-change prompt during live demos.
- **`envsubst` for Prometheus credentials** -- simplest approach to inject Basic Auth into Prometheus config without extra tooling.
- **`start.sh` wrapper** -- ergonomic startup that reads from existing `secrets.env`.

---

## 4. Out of Scope

- Debate feature metrics (debate_arguments_total, etc.) -- can be added later
- Persistent metric storage across server restarts -- metrics reset with the app, which is fine for live workshop demos
- Remote/cloud Grafana -- local only for now
