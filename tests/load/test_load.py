"""
Load test: N participants connect simultaneously, host fires a poll,
all vote randomly, scores are verified correct, leaderboard is printed.

Local:  pytest test_load.py -v -s
Prod:   LOAD_TEST_URL=https://interact.victorrentea.ro pytest test_load.py -v -s
Scale:  LOAD_TEST_COUNT=300 LOAD_TEST_URL=... pytest test_load.py -v -s
"""

import asyncio
import json
import os
import random
import re
import subprocess
import sys
import threading
import time

import certifi
import pytest
import requests
import ssl
import websockets

LOAD_TEST_URL = os.environ.get("LOAD_TEST_URL")
LOAD_TEST_COUNT = int(os.environ.get("LOAD_TEST_COUNT", "30"))

import auth  # noqa: loads shared secrets into os.environ
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


@pytest.fixture(scope="module")
def server_url():
    if LOAD_TEST_URL:
        # Fetch active session from the remote server
        r = requests.get(f"{LOAD_TEST_URL}/api/session/active")
        r.raise_for_status()
        _load_session_id[0] = r.json().get("session_id")
        yield LOAD_TEST_URL
        return
    server_env = os.environ.copy()
    server_env["HOST_USERNAME"] = HOST_USER
    server_env["HOST_PASSWORD"] = HOST_PASS
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=server_env,
    )
    port = None
    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stderr.readline().decode("utf-8", errors="replace")
        m = re.search(r"127\.0\.0\.1:(\d+)", line)
        if m:
            port = int(m.group(1))
            break
        if proc.poll() is not None:
            raise RuntimeError("uvicorn exited unexpectedly during startup")
    else:
        proc.terminate()
        raise RuntimeError("uvicorn did not log a bound port within 15s")
    threading.Thread(target=proc.stderr.read, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}"

    # Create a session so session-scoped participant routes are accessible
    r = requests.post(
        f"{base_url}/api/session/start",
        auth=(HOST_USER, HOST_PASS),
        json={"name": "load-test", "type": "workshop"},
    )
    r.raise_for_status()
    _load_session_id[0] = r.json().get("session_id")

    yield base_url
    proc.terminate()
    proc.wait(timeout=5)


_load_session_id = [None]


def _shost(base_url, method, path, **kwargs):
    """Session-scoped authenticated API call for load tests."""
    sid = _load_session_id[0] or ""
    return _host(base_url, method, f"/api/{sid}{path}", **kwargs)


def _host(base_url, method, path, **kwargs):
    """Authenticated API call to a host-only endpoint."""
    return getattr(requests, method)(
        f"{base_url}{path}",
        auth=(HOST_USER, HOST_PASS),
        **kwargs,
    )


async def _recv_until(ws, predicate, timeout=20.0):
    """Read WebSocket messages until predicate(msg) is True. Returns matching message."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError("Timed out waiting for expected message")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        if predicate(msg):
            return msg


async def participant_task(ws_base, name, idx, counter, n, connected_event, poll_ready_event, results, ssl_ctx=None):
    """
    Lifecycle for one load-test participant:
    1. Stagger connect (idx * 50ms) to avoid broadcast storm on simultaneous connections
    2. Connect via real WebSocket
    3. Receive initial state (fail fast on name_taken)
    4. Wait for poll_ready_event
    5. Drain until poll_active == True
    6. Vote randomly
    7. Drain until vote_update (confirmation)
    8. Drain until scores broadcast
    """
    await asyncio.sleep(idx * 0.05)  # stagger: spread connections over n*50ms to avoid write-buffer overflow
    try:
        async with websockets.connect(f"{ws_base}/ws/{name}", ping_interval=None, ssl=ssl_ctx) as ws:
            # Send set_name as required by the WS handler before state is sent
            await ws.send(json.dumps({"type": "set_name", "name": name}))

            # Drain messages until we get state (participant_count broadcasts from concurrent
            # connections may arrive before our own state message)
            initial_state = None
            for _ in range(50):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15.0))
                if msg.get("type") == "name_taken":
                    raise RuntimeError(f"Name '{name}' already taken on server")
                if msg.get("type") == "state":
                    initial_state = msg
                    break
            if initial_state is None:
                raise RuntimeError(f"{name}: never received initial state message")

            # Signal: I'm connected
            counter["count"] += 1
            if counter["count"] == n:
                connected_event.set()

            # Wait for host to open the poll
            await poll_ready_event.wait()

            # Drain until poll is active
            msg = await _recv_until(
                ws,
                lambda m: m.get("type") == "state" and m.get("poll_active") and m.get("poll"),
                timeout=20.0,
            )

            # Vote for a random option
            options = msg["poll"]["options"]
            chosen = random.choice(options)
            voted_id = chosen["id"]
            await ws.send(json.dumps({"type": "vote", "option_id": voted_id}))

            # Drain until vote_update — any vote_update after our send means our vote landed
            await _recv_until(ws, lambda m: m.get("type") == "vote_update", timeout=20.0)
            results[name]["voted"] = True
            results[name]["voted_id"] = voted_id

            # Drain until individual "result" message (sent after correct_ids are set)
            result_msg = await _recv_until(
                ws,
                lambda m: m.get("type") == "result",
                timeout=30.0,
            )
            results[name]["score"] = result_msg.get("score", 0)
            results[name]["done"] = True

    except Exception as exc:
        results[name]["error"] = str(exc)


@pytest.mark.load
def test_load(server_url):
    n = LOAD_TEST_COUNT
    ws_base = server_url.replace("http://", "ws://").replace("https://", "wss://")
    ssl_ctx = ssl.create_default_context(cafile=certifi.where()) if ws_base.startswith("wss://") else None

    # Pre-condition: no active poll (avoids disrupting a live session on prod)
    status = requests.get(f"{server_url}/api/status").json()
    if status.get("poll") is not None:
        pytest.skip("Server already has an active poll — skipping load test")

    results = {
        f"LBT{i:03d}": {"voted": False, "voted_id": None, "score": None, "done": False, "error": None}
        for i in range(n)
    }

    async def _run():
        connected_event = asyncio.Event()
        poll_ready_event = asyncio.Event()
        counter = {"count": 0}

        tasks = [
            asyncio.create_task(
                participant_task(ws_base, f"LBT{i:03d}", i, counter, n, connected_event, poll_ready_event, results, ssl_ctx)
            )
            for i in range(n)
        ]

        # Phase 1: wait for all participants to connect (allow extra time for stagger + TLS on prod)
        await asyncio.wait_for(connected_event.wait(), timeout=max(30.0, n * 0.1 + 20.0))
        print(f"\n✓ All {n} participants connected")

        # Phase 2: host creates and opens poll
        # Use asyncio.to_thread so requests don't block the event loop (participant ping/pong)
        poll_resp = await asyncio.to_thread(
            lambda: _shost(server_url, "post", "/poll", json={
                "question": "Load test poll — pick any option",
                "options": ["Option A", "Option B", "Option C", "Option D"],
            })
        )
        assert poll_resp.status_code == 200, f"create_poll failed: {poll_resp.text}"
        correct_id = poll_resp.json()["poll"]["options"][0]["id"]  # opt0 is the "correct" answer

        await asyncio.to_thread(lambda: _shost(server_url, "put", "/poll/status", json={"open": True}))
        poll_ready_event.set()
        print(f"✓ Poll opened — {n} participants voting...")

        loop = asyncio.get_running_loop()

        # Phase 3: wait for all votes
        deadline = loop.time() + 60.0
        while True:
            voted_count = sum(1 for r in results.values() if r["voted"])
            if voted_count == n:
                break
            if loop.time() > deadline:
                raise TimeoutError(f"Only {voted_count}/{n} voted within 30s")
            await asyncio.sleep(0.1)
        print(f"✓ All {n} votes cast")

        # Phase 4: close poll and post correct answer → triggers scores broadcast
        await asyncio.to_thread(lambda: _shost(server_url, "put", "/poll/status", json={"open": False}))
        await asyncio.to_thread(lambda: _shost(server_url, "put", "/poll/correct", json={"correct_ids": [correct_id]}))
        print("✓ Poll closed, correct answer posted")

        # Phase 5: wait for all scores received
        deadline = loop.time() + 30.0
        while True:
            done_count = sum(1 for r in results.values() if r["done"])
            if done_count == n:
                break
            if loop.time() > deadline:
                raise TimeoutError(f"Only {done_count}/{n} received scores within 15s")
            await asyncio.sleep(0.1)

        await asyncio.gather(*tasks)
        return correct_id

    try:
        correct_id = asyncio.run(_run())
    finally:
        # Teardown: always clean up server state (essential for prod)
        try:
            _shost(server_url, "delete", "/poll")
        except Exception as exc:
            print(f"  [warn] DELETE /api/poll failed during teardown: {exc}")
        try:
            _shost(server_url, "delete", "/scores")
        except Exception as exc:
            print(f"  [warn] DELETE /api/scores failed during teardown: {exc}")

    # ── Assertions ──────────────────────────────────────────────────────────

    errors = [(pname, r["error"]) for pname, r in results.items() if r.get("error")]
    assert not errors, "Participant errors:\n" + "\n".join(f"  {pname}: {err}" for pname, err in errors)

    assert all(r["voted"] for r in results.values()), "Not all participants cast a vote"
    assert all(r["done"] for r in results.values()), "Not all participants received scores"

    for name, r in results.items():
        if r["voted_id"] == correct_id:
            assert r["score"] is not None and r["score"] >= 500, (
                f"{name} voted correctly (opt0) but score={r['score']} — expected >= 500 (_MIN_POINTS)"
            )
        else:
            assert r["score"] is not None and r["score"] == 0, (
                f"{name} voted wrong but score={r['score']} — expected 0"
            )

    assert requests.get(f"{server_url}/api/status").status_code == 200, "Server unresponsive after load test"

    # ── Leaderboard ─────────────────────────────────────────────────────────
    sorted_results = sorted(results.items(), key=lambda x: x[1].get("score") or 0, reverse=True)
    print(f"\n=== Leaderboard ({n} participants) ===")
    for rank, (name, r) in enumerate(sorted_results, 1):
        mark = "✓" if r["voted_id"] == correct_id else "✗"
        print(f"  {rank:3}. {name:10} {r.get('score', 0):5} pts  {mark}")
