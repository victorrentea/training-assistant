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

import pytest
import requests
import websockets

LOAD_TEST_URL = os.environ.get("LOAD_TEST_URL")
LOAD_TEST_COUNT = int(os.environ.get("LOAD_TEST_COUNT", "30"))

import auth  # noqa: loads secrets.env into os.environ
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


@pytest.fixture(scope="module")
def server_url():
    if LOAD_TEST_URL:
        yield LOAD_TEST_URL
        return
    server_env = os.environ.copy()
    server_env["HOST_USERNAME"] = HOST_USER
    server_env["HOST_PASSWORD"] = HOST_PASS
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.abspath(__file__)),
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
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=5)


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


async def participant_task(ws_base, name, counter, n, connected_event, poll_ready_event, results):
    """
    Lifecycle for one load-test participant:
    1. Connect via real WebSocket
    2. Receive initial state (fail fast on name_taken)
    3. Wait for poll_ready_event
    4. Drain until poll_active == True
    5. Vote randomly
    6. Drain until vote_update (confirmation)
    7. Drain until scores broadcast
    """
    try:
        async with websockets.connect(f"{ws_base}/ws/{name}") as ws:
            # Receive initial message
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=15.0))
            if first.get("type") == "name_taken":
                raise RuntimeError(f"Name '{name}' already taken on server")
            assert first.get("type") == "state", f"Unexpected first message type: {first.get('type')}"

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

            # Drain until scores broadcast (type == "scores", NOT vote_update)
            scores_msg = await _recv_until(ws, lambda m: m.get("type") == "scores", timeout=30.0)
            results[name]["score"] = scores_msg["scores"].get(name, 0)
            results[name]["done"] = True

    except Exception as exc:
        results[name]["error"] = str(exc)


@pytest.mark.load
def test_load(server_url):
    assert requests.get(f"{server_url}/api/status").status_code == 200
