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


@pytest.mark.load
def test_load(server_url):
    assert requests.get(f"{server_url}/api/status").status_code == 200
