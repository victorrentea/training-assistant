# Load Test Design — Task 115

**Date:** 2026-03-20
**Goal:** Verify the Workshop Interact server can handle 30–300 concurrent participants — connect simultaneously, receive a live poll, vote randomly, accumulate scores.

---

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `LOAD_TEST_URL` | _(spin up local uvicorn)_ | Target URL; set to prod to skip local server |
| `LOAD_TEST_COUNT` | `30` | Number of concurrent participants |

`HOST_USERNAME` / `HOST_PASSWORD` are read from `secrets.env` (same as other tests).

---

## File

**`test_load.py`** — single pytest test, marker `load`, added to `run_tests.sh`.
No new dependencies (`websockets>=12.0` already in `pyproject.toml`).

---

## Participant Lifecycle (asyncio task per participant)

1. `websockets.connect(ws_url/ws/{name})` — real TCP WebSocket
2. Receive initial `state` message → increment shared counter; if counter == N, set `all_connected_event`
3. `await poll_ready_event` (set by main after host opens the poll)
4. Drain WebSocket messages until `poll_active == True` in a state broadcast
5. Pick a random option; send `{"type": "vote", "option_id": "..."}`
6. Receive `vote_update` confirmation → signal voted
7. Drain messages until `scores` broadcast includes own name → store score
8. Close WebSocket

---

## Main Coroutine (orchestration)

```
launch N asyncio tasks
await all_connected_event          # 15s timeout
host POST /api/poll                # create poll
host POST /api/poll/status open    # open voting → set poll_ready_event
await all_voted_event              # 30s timeout
host POST /api/poll/status close   # close voting
host POST /api/poll/correct        # mark first option correct
await all_scored_event             # 15s timeout
run assertions
print leaderboard
```

---

## Assertions

1. `len(results) == N` — all participants completed without exception
2. `sum(voted) == N` — every vote was accepted
3. Participants who voted for the **correct** option: `score > 0`
4. Participants who voted for a **wrong** option: `score == 0`
5. `GET /api/status` returns 200 — server alive after load

---

## Leaderboard Output (stdout)

```
=== Leaderboard (30 participants) ===
  1. Frodo               850 pts  ✓
  2. Gandalf             720 pts  ✓
  ...
 28. Sauron                0 pts  ✗
```

Sorted descending by score. `✓` = voted correctly, `✗` = voted wrong.
No assertion on exact scores (Kahoot-style timing means each correct voter scores differently).

---

## Scalability

Changing `LOAD_TEST_COUNT=300` requires zero code changes. asyncio tasks are cheap; the bottleneck is the server's single-threaded event loop — which is exactly what we're testing.

---

## Prod Execution

```bash
# 30 participants
LOAD_TEST_URL=https://interact.victorrentea.ro LOAD_TEST_COUNT=30 pytest test_load.py -v -s

# 300 participants
LOAD_TEST_URL=https://interact.victorrentea.ro LOAD_TEST_COUNT=300 pytest test_load.py -v -s
```
