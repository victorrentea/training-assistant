# WordCloud Load Test — JMeter

## What it tests

- **301 WebSocket connections** to `interact.victorrentea.ro`:
  - 300 participant connections (unauthenticated, random UUIDs)
  - 1 host connection (`/ws/__host__`)
- All 300 participants are synchronized via a `SyncTimer`, then each sends
  **1 word per second** for `NUM_ROUNDS` rounds (default: 5).
- **Assertion 1** — no crashes: all WS open/send operations must succeed
  (tracked via JMeter's built-in error rate).
- **Assertion 2** — consistent delivery: every participant **and** the host
  must receive exactly `NUM_PARTICIPANTS × NUM_ROUNDS` state-type broadcasts
  after the sync point.

## Prerequisites

### JMeter 5.5+

Download from https://jmeter.apache.org/download_jmeter.cgi

### Required plugins — drop JARs into `$JMETER_HOME/lib/ext/`

| Plugin | JAR | Source |
|--------|-----|--------|
| WS Samplers (Peter Doornbosch) | `jmeter-websocket-samplers-*.jar` | https://bitbucket.org/pjtr/jmeter-websocket-samplers/downloads/ |
| SyncTimer (JMeter Plugins) | `jmeter-plugins-casutg-*.jar` | https://jmeter-plugins.org/wiki/ConcurrencyThreadGroup/ |

Alternatively install both via the **JMeter Plugin Manager**
(`jmeter-plugins-manager-*.jar` in `lib/ext/` → Options menu → Plugin Manager).

## Configuration

Open `wordcloud-load-test.jmx` in JMeter GUI and edit **User Defined Variables**:

| Variable | Default | Notes |
|---|---|---|
| `HOST` | `interact.victorrentea.ro` | Target server |
| `WS_PORT` | `443` | 443 for production (wss) |
| `USE_SSL` | `true` | Set `false` + port `8000` for localhost |
| `AUTH_USER` | `CHANGE_ME` | From `secrets.env` → `HOST_USERNAME` |
| `AUTH_PASS` | `CHANGE_ME` | From `secrets.env` → `HOST_PASSWORD` |
| `NUM_PARTICIPANTS` | `300` | **Must match SyncTimer GroupSize** |
| `NUM_ROUNDS` | `5` | Words per participant (1/sec) |
| `RAMP_UP_SEC` | `30` | Connection ramp-up (0 = instant) |
| `DRAIN_TIMEOUT_MS` | `5000` | Silence period signalling end of drain |

## Running

### GUI mode (for debugging / small runs)

```bash
$JMETER_HOME/bin/jmeter -t load-tests/wordcloud-load-test.jmx
```

Enable the "View Results Tree" listener (disabled by default) for per-message detail.

### CLI mode (for actual load test)

```bash
$JMETER_HOME/bin/jmeter \
  -n \
  -t load-tests/wordcloud-load-test.jmx \
  -l load-tests/results/wordcloud-run.jtl \
  -e -o load-tests/results/report \
  -JAUTH_USER=<user> -JAUTH_PASS=<pass>
```

The HTML report is generated in `load-tests/results/report/`.

## Test flow timeline

```
T-30s .. T=0s   Ramp: 300 participants connect and set_name
                Pre-sync drain: flush participant_count noise
T=0             SyncTimer fires — all 300 threads released simultaneously
T=0..4s         All 300 send 1 word/sec × 5 rounds → 1500 broadcasts total
T=5s            Send loop done; each client drains buffered broadcasts
T=5+5s          DRAIN_TIMEOUT_MS silence → drain ends
Teardown        Global assertion: host + all 300 participants = 1500 state msgs
```

## Assertion details

### Per-thread assertion (during test)
Each participant thread asserts its own received `type="state"` count equals
`NUM_PARTICIPANTS × NUM_ROUNDS`. Failure appears as a failed sample in the
JMeter results tree.

### Global assertion (teardown)
Compares the host count against the same expected value and logs a single
`PASS` or `FAIL` line summarising all 301 clients.

## Tuning tips

- If participants miss messages, increase `DRAIN_TIMEOUT_MS` (5 s is conservative).
- Reduce `NUM_PARTICIPANTS` / `NUM_ROUNDS` for quick smoke tests.
- Set `RAMP_UP_SEC=0` to maximise connection-phase concurrency (stress test).
- JMeter needs adequate heap for 300 WS connections:
  ```bash
  export JVM_ARGS="-Xms512m -Xmx2g"
  ```
