#!/usr/bin/env python3
"""Fan-out benchmark for the Railway relay during a conference talk.

NOT a pytest test (no ``test_`` prefix, never collected). It replays what a
400-500 phone talk does to the relay and prints numbers:

1. Join storm: N phones join within --join-window seconds the way
   static/talk.html does (page, register, /api/slides, WebSocket, state), all
   from ONE source IP like a venue NAT. Reports time-to-join, WS accept time and
   HTTP errors (429s ...). A phone that gets 429 on the page retries after 1 s,
   like a person hitting reload.
2. K stalled phones: raw sockets that finish the WS handshake, then never read
   (tiny receive buffer + small MSS) — a phone that went dark. A fill phase then
   broadcasts enough data to fill their buffers, which on a real talk takes
   minutes of slide/emoji traffic.
3. A stub daemon (it plays the trainer's daemon on /ws/daemon) broadcasts
   ``current_slide_updated`` every --interval seconds and the bench reports the
   delivery latency to every healthy phone (p50/p95/max), plus the round trip of
   a proxied participant REST call (/api/participant/state) issued meanwhile.

Local run (starts its own single-worker uvicorn with railway.toml's WS flags,
bound to a non-loopback address so the per-IP rate limiter is active):

    uv run --extra dev python tests/load/talk_fanout_bench.py
    uv run --extra dev python tests/load/talk_fanout_bench.py --participants 500 --stalled 3
    # what the join storm looked like with the old rate-limit defaults:
    RATE_LIMIT_CAPACITY=60 RATE_LIMIT_REFILL_PER_SEC=15 uv run --extra dev python tests/load/talk_fanout_bench.py

Against an already deployed NON-production instance:

    HOST_USERNAME=... HOST_PASSWORD=... uv run --extra dev python \\
        tests/load/talk_fanout_bench.py --base-url https://my-staging.up.railway.app

The stub daemon takes over /ws/daemon (kicking any real daemon) and announces
its own session — never point this at production.
"""
import argparse
import asyncio
import base64
import json
import os
import random
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_ALPHABET = "abcdefghijkmnpqrstuvwxyz123456789"
FILL_CHUNK_BYTES = 64 * 1024
SLIDE_PREFIX = '{"type": "current_slide_updated"'
now = time.perf_counter  # uvloop's loop.time() only has millisecond resolution
FILL_PREFIX = '{"type": "bench_fill"'


# ── helpers ─────────────────────────────────────────────────────────────────

def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q / 100 * (len(ordered) - 1))))]


def ms_summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    return (f"p50 {percentile(values, 50) * 1000:7.1f} ms   p95 {percentile(values, 95) * 1000:7.1f} ms"
            f"   max {max(values) * 1000:7.1f} ms   (n={len(values)})")


def primary_ip() -> str | None:
    """This machine's non-loopback address (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            return None if ip.startswith("127.") else ip
    except OSError:
        return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def raise_fd_limit() -> None:
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
    except (ImportError, ValueError, OSError):
        pass


class LocalServer:
    """uvicorn railway.app:app, single worker, same WS flags as railway.toml."""

    def __init__(self, host_user: str, host_pass: str):
        self.port = free_port()
        ip = primary_ip()
        # Loopback peers are exempt from the rate limiter; a non-loopback address
        # makes the join storm hit it like a venue NAT would.
        self.connect_host = ip or "127.0.0.1"
        self.base_url = f"http://{self.connect_host}:{self.port}"
        self.log_path = Path(tempfile.gettempdir()) / f"talk_fanout_bench_uvicorn_{self.port}.log"
        env = {**os.environ, "HOST_USERNAME": host_user, "HOST_PASSWORD": host_pass}
        self._log = self.log_path.open("w")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "railway.app:app", "--host", "0.0.0.0",
             "--port", str(self.port), "--ws-ping-interval", "20", "--ws-ping-timeout", "60"],
            cwd=REPO_ROOT, env=env, stdout=self._log, stderr=subprocess.STDOUT,
        )

    async def wait_ready(self, client: httpx.AsyncClient) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"uvicorn exited early, see {self.log_path}")
            try:
                if (await client.get(f"{self.base_url}/api/status")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)
        raise RuntimeError(f"uvicorn not ready in 30 s, see {self.log_path}")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._log.close()


# ── stub daemon ─────────────────────────────────────────────────────────────

class StubDaemon:
    """Plays the trainer's daemon: announces a talk session, answers proxy
    requests at once and broadcasts what the bench tells it to."""

    def __init__(self, ws_base: str, auth: str, session_id: str, ws_kwargs: dict):
        self.url = f"{ws_base}/ws/daemon"
        self.auth = auth
        self.session_id = session_id
        self.ws_kwargs = ws_kwargs
        self.outbox: asyncio.Queue[str] = asyncio.Queue()
        self.proxy_requests = 0
        self.presence_messages = 0
        self.page = 1
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        ws = await ws_connect(self.url, additional_headers={"Authorization": self.auth},
                              max_size=None, **self.ws_kwargs)
        await ws.send(json.dumps({"type": "set_session_id", "session_id": self.session_id,
                                  "session_type": "talk"}))
        self.task = asyncio.gather(self._sender(ws), self._receiver(ws))

    def broadcast(self, event: dict) -> None:
        self.outbox.put_nowait(json.dumps({"type": "broadcast", "event": event}))

    async def _sender(self, ws: ClientConnection) -> None:
        while True:
            await ws.send(await self.outbox.get())

    async def _receiver(self, ws: ClientConnection) -> None:
        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "proxy_request":
                self.proxy_requests += 1
                self.outbox.put_nowait(json.dumps(self._answer(msg)))
            elif kind == "participant_presence":
                self.presence_messages += 1

    def _answer(self, req: dict) -> dict:
        path = req.get("path") or ""
        if path.endswith("/api/participant/state"):
            body: dict = {"slides_current": {"slug": "bench", "page": self.page}, "emoji_counters": {}}
        elif path.endswith("/api/slides"):
            body = {"slides": []}
        else:
            body = {"ok": True}
        return {"type": "proxy_response", "id": req["id"], "status": 200,
                "body": json.dumps(body), "content_type": "application/json"}


# ── phones ──────────────────────────────────────────────────────────────────

class Phone:
    """A healthy talk.html participant."""

    def __init__(self, idx: int):
        self.uuid = f"bench-{idx:04d}-{secrets.token_hex(4)}"
        self.ws: ClientConnection | None = None
        self.reader: asyncio.Task | None = None
        self.slides_at: dict[int, float] = {}
        self.fills = 0
        self.closed_code: int | None = None
        self.join_s: float | None = None
        self.ws_accept_s: float | None = None
        self.page_429s = 0
        self.error: str | None = None

    async def join(self, ctx: "Bench") -> None:
        started = now()
        headers = {"X-Participant-ID": self.uuid}
        try:
            for _ in range(ctx.args.max_page_retries + 1):  # the QR code URL
                r = await ctx.http.get(f"{ctx.base}/{ctx.sid}", follow_redirects=True)
                ctx.statuses[("page", r.status_code)] += 1
                if r.status_code != 429:
                    break
                self.page_429s += 1
                await asyncio.sleep(1 + random.random())  # person hits reload
            if r.status_code != 200:
                raise RuntimeError(f"page {r.status_code}")
            if ctx.args.page == "participant":  # participant.html also probes /api/status
                r = await ctx.http.get(f"{ctx.base}/api/status")
                ctx.statuses[("status", r.status_code)] += 1
            r = await ctx.http.post(f"{ctx.base}/{ctx.sid}/api/participant/register",
                                    headers=headers, json={"name": "Viewer"})
            ctx.statuses[("register", r.status_code)] += 1
            r = await ctx.http.get(f"{ctx.base}/{ctx.sid}/api/slides")
            ctx.statuses[("slides", r.status_code)] += 1
            ws_started = now()
            self.ws = await ws_connect(f"{ctx.ws_base}/ws/{ctx.sid}/{self.uuid}", max_size=None,
                                       ping_interval=None, open_timeout=60, **ctx.ws_kwargs)
            self.ws_accept_s = now() - ws_started
            await self.ws.send(json.dumps({"type": "set_name", "name": "Viewer"}))
            self.reader = asyncio.create_task(self._read(self.ws))
            r = await ctx.http.get(f"{ctx.base}/{ctx.sid}/api/participant/state", headers=headers)
            ctx.statuses[("state", r.status_code)] += 1
            self.join_s = now() - started
        except Exception as exc:  # noqa: BLE001 — every failure is a data point
            self.error = f"{type(exc).__name__}: {exc}"[:120]

    async def _read(self, ws: ClientConnection) -> None:
        try:
            async for raw in ws:
                if not isinstance(raw, str):
                    continue
                if raw.startswith(FILL_PREFIX):
                    self.fills += 1
                elif raw.startswith(SLIDE_PREFIX):
                    self.slides_at[json.loads(raw)["bench_seq"]] = now()
        except ConnectionClosed:
            pass
        self.closed_code = ws.close_code if ws.close_code is not None else -1


def open_stalled_phone(base_url: str, path: str) -> socket.socket:
    """A WebSocket that never reads after the handshake (blocking, run in a thread)."""
    url = urlparse(base_url)
    port = url.port or (443 if url.scheme == "https" else 80)
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    try:  # small MSS: the server's send buffer stays small, so it fills fast
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, 536)
    except (AttributeError, OSError):
        pass
    raw.settimeout(15)
    raw.connect((url.hostname, port))
    sock: socket.socket = raw
    if url.scheme == "https":
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=url.hostname)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {url.netloc}\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                  f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(1)  # byte by byte: leave every frame after the 101 unread
        if not chunk:
            raise RuntimeError("stalled phone: connection closed during handshake")
        head += chunk
    if b" 101 " not in head.split(b"\r\n", 1)[0]:
        raise RuntimeError(f"stalled phone: no upgrade: {head[:60]!r}")
    return sock


# ── the bench ───────────────────────────────────────────────────────────────

class Bench:
    def __init__(self, args: argparse.Namespace, base: str, http: httpx.AsyncClient,
                 ws_kwargs: dict, auth: str):
        self.args = args
        self.base = base.rstrip("/")
        self.ws_base = self.base.replace("https://", "wss://").replace("http://", "ws://")
        self.http = http
        self.ws_kwargs = ws_kwargs
        self.sid = args.session_id or "".join(secrets.choice(SESSION_ALPHABET) for _ in range(6))
        self.statuses: Counter = Counter()
        self.auth = auth
        self.daemon = StubDaemon(self.ws_base, self.auth, self.sid, ws_kwargs)
        self.phones = [Phone(i) for i in range(args.participants)]
        self.stalled: list[socket.socket] = []

    async def wait_session_active(self) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            r = await self.http.get(f"{self.base}/{self.sid}/api/status")
            if r.status_code == 200 and r.json().get("session_active"):
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("session never became active")

    async def join_storm(self) -> None:
        start = now()
        n = len(self.phones)

        async def _join_at(i: int, phone: Phone) -> None:
            await asyncio.sleep(max(0.0, start + i * self.args.join_window / n - now()))
            await phone.join(self)

        await asyncio.gather(*(_join_at(i, p) for i, p in enumerate(self.phones)))
        elapsed = now() - start
        ok = [p for p in self.phones if p.error is None]
        print(f"\n== Join storm: {n} phones within {self.args.join_window:.0f}s, one source IP ==")
        print(f"  joined           {len(ok)}/{n} in {elapsed:.1f}s")
        print(f"  time to join     {ms_summary([p.join_s for p in ok if p.join_s is not None])}")
        print(f"  WS accept        {ms_summary([p.ws_accept_s for p in ok if p.ws_accept_s is not None])}")
        retried = [p for p in self.phones if p.page_429s]
        print(f"  page 429s        {sum(p.page_429s for p in self.phones)} "
              f"({len(retried)} phones had to reload at least once)")
        print("  HTTP statuses    " + ", ".join(f"{k[0]} {k[1]}: {v}" for k, v in sorted(self.statuses.items())))
        errors = Counter(p.error for p in self.phones if p.error)
        for err, count in errors.most_common(5):
            print(f"  error x{count}: {err}")

    async def open_stalled(self) -> None:
        for i in range(self.args.stalled):
            path = f"/ws/{self.sid}/stalled-{i}-{secrets.token_hex(3)}"
            self.stalled.append(await asyncio.to_thread(open_stalled_phone, self.base, path))

    def live_phones(self) -> list[Phone]:
        return [p for p in self.phones if p.ws is not None and p.closed_code is None]

    async def fill(self) -> None:
        """Fill the stalled phones' buffers (what minutes of real traffic would do)."""
        chunks = max(1, self.args.fill_kb * 1024 // FILL_CHUNK_BYTES)
        pad = "x" * FILL_CHUNK_BYTES
        started = now()
        for _ in range(chunks):
            self.daemon.broadcast({"type": "bench_fill", "pad": pad})
        phones = self.live_phones()
        while now() - started < self.args.fill_timeout:
            if all(p.fills >= chunks for p in phones):
                break
            await asyncio.sleep(0.05)
        done = sum(p.fills >= chunks for p in phones)
        took = now() - started
        print(f"\n== Fill: {chunks} x {FILL_CHUNK_BYTES // 1024} KB broadcasts ==")
        print(f"  all of it reached {done}/{len(phones)} healthy phones after {took:.1f}s"
              + ("" if done == len(phones) else f" (gave up waiting at {self.args.fill_timeout:.0f}s)"))

    async def probe_proxy(self, stop: asyncio.Event, rtts: list[float], statuses: Counter) -> None:
        headers = {"X-Participant-ID": self.phones[0].uuid}
        while not stop.is_set():
            started = now()
            try:
                r = await self.http.get(f"{self.base}/{self.sid}/api/participant/state",
                                        headers=headers, timeout=15)
                statuses[r.status_code] += 1
            except httpx.HTTPError as exc:
                statuses[type(exc).__name__] += 1
            rtts.append(now() - started)
            await asyncio.sleep(self.args.interval)

    async def slide_broadcasts(self) -> None:
        phones = self.live_phones()
        rtts: list[float] = []
        proxy_statuses: Counter = Counter()
        stop = asyncio.Event()
        probe = asyncio.create_task(self.probe_proxy(stop, rtts, proxy_statuses))
        sent_at: dict[int, float] = {}
        for seq in range(1, self.args.broadcasts + 1):
            self.daemon.page = seq
            sent_at[seq] = now()
            self.daemon.broadcast({"type": "current_slide_updated",
                                   "current_slide": {"slug": "bench", "page": seq}, "bench_seq": seq})
            await asyncio.sleep(self.args.interval)
        deadline = now() + self.args.deadline
        while now() < deadline and not all(len(p.slides_at) >= len(sent_at) for p in phones):
            await asyncio.sleep(0.05)
        stop.set()
        await probe

        latencies: list[float] = []
        worst_per_broadcast: list[float] = []
        missing = 0
        for seq, t0 in sent_at.items():
            got = [p.slides_at[seq] - t0 for p in phones if seq in p.slides_at]
            missing += len(phones) - len(got)
            latencies.extend(got)
            worst_per_broadcast.append(max(got) if got else float("inf"))
        print(f"\n== Slide broadcasts: {len(sent_at)} x current_slide_updated every "
              f"{self.args.interval * 1000:.0f} ms to {len(phones)} healthy phones ==")
        print(f"  delivery latency {ms_summary(latencies)}")
        print(f"  not delivered    {missing} of {len(sent_at) * len(phones)} "
              f"within {self.args.deadline:.0f}s after the last broadcast")
        print("  worst per bcast  " + " ".join(
            "never" if w == float("inf") else f"{w * 1000:.0f}" for w in worst_per_broadcast) + " (ms)")
        print(f"  proxied REST     {ms_summary(rtts)}")
        print("  proxied statuses " + ", ".join(f"{k}: {v}" for k, v in sorted(proxy_statuses.items(), key=str)))

    async def run(self) -> None:
        print(f"target {self.base}  session {self.sid}  page {self.args.page}  "
              f"phones {self.args.participants}  stalled {self.args.stalled}")
        await self.daemon.start()
        await self.wait_session_active()
        await self.join_storm()
        await self.open_stalled()
        await asyncio.sleep(1.5)  # let presence + count broadcasts settle
        await self.fill()
        await self.slide_broadcasts()
        dropped = [p for p in self.phones if p.ws is not None and p.closed_code is not None]
        print(f"\n  healthy phones disconnected during the run: {len(dropped)}")
        print(f"  stub daemon: {self.daemon.proxy_requests} proxy requests answered, "
              f"{self.daemon.presence_messages} presence messages")

    async def close(self) -> None:
        for sock in self.stalled:
            sock.close()
        await asyncio.gather(*(p.ws.close() for p in self.phones if p.ws is not None),
                             return_exceptions=True)
        if self.daemon.task is not None:
            self.daemon.task.cancel()
            await asyncio.gather(self.daemon.task, return_exceptions=True)


async def main(args: argparse.Namespace) -> None:
    raise_fd_limit()
    user = os.environ.get("HOST_USERNAME") or args.host_user
    pw = os.environ.get("HOST_PASSWORD") or args.host_pass
    auth = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    server = None
    if args.base_url is None:
        server = LocalServer(user, pw)
        base = server.base_url
        # Never route the local target through an HTTP(S)_PROXY from the environment.
        http = httpx.AsyncClient(timeout=60, trust_env=False,
                                 limits=httpx.Limits(max_connections=None, max_keepalive_connections=None))
        ws_kwargs: dict = {"proxy": None}
    else:
        base = args.base_url
        http = httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=None,
                                                                 max_keepalive_connections=None))
        ws_kwargs = {}
    bench = None
    try:
        if server is not None:
            await server.wait_ready(http)
        bench = Bench(args, base, http, ws_kwargs, auth)
        await bench.run()
    finally:
        if bench is not None:
            await bench.close()
        await http.aclose()
        if server is not None:
            server.stop()
            print(f"\n(uvicorn log: {server.log_path})")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base-url", help="target an already running instance (never production)")
    p.add_argument("--participants", type=int, default=500)
    p.add_argument("--stalled", type=int, default=3, help="phones that stop reading")
    p.add_argument("--join-window", type=float, default=5.0, help="seconds over which phones join")
    p.add_argument("--max-page-retries", type=int, default=20)
    p.add_argument("--page", choices=["talk", "participant"], default="talk",
                   help="participant also hits /api/status like participant.html")
    p.add_argument("--fill-kb", type=int, default=384, help="broadcast data to fill stalled buffers")
    p.add_argument("--fill-timeout", type=float, default=15.0)
    p.add_argument("--broadcasts", type=int, default=20)
    p.add_argument("--interval", type=float, default=0.25, help="seconds between slide changes")
    p.add_argument("--deadline", type=float, default=6.0,
                   help="seconds to wait for deliveries after the last broadcast")
    p.add_argument("--session-id", help="defaults to a random 6-char id")
    p.add_argument("--host-user", default="bench", help="local server only (env HOST_USERNAME wins)")
    p.add_argument("--host-pass", default="bench", help="local server only (env HOST_PASSWORD wins)")
    return p.parse_args()


if __name__ == "__main__":
    try:
        import uvloop  # same loop uvicorn uses on Railway; keeps client overhead low
    except ImportError:
        uvloop = None
    (uvloop.run if uvloop else asyncio.run)(main(parse_args()))
