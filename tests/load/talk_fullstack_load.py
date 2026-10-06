#!/usr/bin/env python3
"""Full-stack load test of a conference talk: real Railway app + real daemon + N phones.

NOT a pytest test (no ``test_`` prefix, never collected). For each N it starts a
fresh stack in this machine, replays what ``static/talk.html`` does on N phones,
and prints / writes hard numbers: requests, latencies, CPU and memory of the
Railway process and of the daemon process (which runs on the trainer's laptop).

Stack (all local, started by this script, torn down after each N):
  * Railway: ``python -m uvicorn railway.app:app`` -- single worker, the WS ping
    flags of railway.toml. Phones connect through this machine's NON-loopback
    address (loopback peers skip the per-IP rate limiter) and all send the same
    ``X-Forwarded-For``: one venue NAT, like in production.
  * Daemon: ``python -m daemon`` configured like tests/docker/start_hermetic.sh
    (stub adapters, temp sessions folder, host credentials), with a one-deck
    slides catalog whose ``drive_export_url`` points at
    tests/docker/mock_drive_server.py serving the --deck PDF. Its single-instance
    lock file is moved to the temp dir so it never fights another local daemon.
  * A mock add-on bridge (the trainer's macOS add-ons): the daemon connects to it,
    it sends ``slide_presenting_now`` (the trainer moving through the deck) and
    counts the ``display_emoji`` frames that reach the projected screen.

Each simulated phone does what talk.html does: GET the page (+ its same-origin
scripts), POST register, open the WebSocket /ws/{sid}/{uuid}, GET state,
GET /api/slides/check/{slug}, then open the PDF like pdf.js with
``disableAutoFetch + disableStream + rangeChunkSize=128 KiB``: a plain GET that
is aborted once the headers arrive, then ~32 Range requests of 128 KiB; every
NEW slide the trainer shows costs 1-2 more ranges (always fetched: conservative).
WS reconnects use talk.html's backoff (250 ms + full jitter) and catch up via
GET state.

Scenarios, per N:
  join       N phones join, spread uniformly over --join-window seconds, while
             the trainer shows slide 1 (the first /check pulls the PDF from Drive).
  steady     --slides slide changes, --slide-interval s apart; two "jokes" where
             40% of the phones send 1-3 reactions within 2 s; a background trickle
             of reactions (1% of the room per second).
  reconnect  20% of the WebSockets drop at once (TCP reset); they come back with
             talk.html's backoff, then one more slide change checks that every
             phone, reconnected ones included, gets it.

Measured: psutil every 0.5 s on the Railway, daemon and load-generator processes
(CPU % avg/peak, CPU-seconds per phase, RSS start/peak/end); requests per
endpoint and status with p50/p95/max latency; WS slide-delivery latency (from
the moment the mock bridge sent the event); PDF bytes served; emoji accepted vs
``display_emoji`` frames that reached the screen; daemon stdout lines per phase.

Run from the repo root (telemetry extra: the daemon's slide /check imports
opentelemetry; uvloop is optional but makes the generator cheaper):

    uv run --extra dev --extra daemon --extra telemetry --with psutil --with uvloop \\
        python tests/load/talk_fullstack_load.py --deck /path/to/deck.pdf \\
        --participants 100 300 500 --out-md /tmp/loadtest-results.md

Logs of every process land in --work-dir (default: a fresh temp dir), printed at
the end. Never point this at production: it only ever starts its own local stack.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import platform
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter, defaultdict
import signal
import ssl
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DECK_TITLE = "Agentic Engineering"
DECK_PPTX = f"{DECK_TITLE}.pptx"
DECK_SLUG = "agentic-engineering"  # the daemon derives it from the title
RANGE_CHUNK = 128 * 1024          # talk.html: RANGE_CHUNK_BYTES = 131072
INITIAL_CHUNKS = 32               # pdf.js reads on open (page dictionaries spread over the file)
NAT_IP = "203.0.113.7"            # every phone behind one venue NAT
HOST_USER, HOST_PASS = "host", "loadtest-pass"
TALK_EMOJIS = ["👏", "❤️", "🔥", "🤯"]
SLIDE_MARK = "current_slide_updated"
now = time.perf_counter

# Current phase label; read by the sampler / log-reader threads.
PHASE = {"name": "setup"}


# ── small helpers ────────────────────────────────────────────────────────────

def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q / 100 * (len(s) - 1))))]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def primary_ip() -> str:
    """This machine's non-loopback address (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    if ip.startswith("127."):
        raise SystemExit("no non-loopback address: the per-IP rate limiter would be bypassed")
    return ip


def raise_fd_limit() -> None:
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
    except (ImportError, ValueError, OSError):
        pass


def clean_env(**extra: str) -> dict:
    """Child env without any HTTP(S) proxy: every hop here is local."""
    env = {k: v for k, v in os.environ.items()
           if "proxy" not in k.lower() and k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    env.update(PYTHONUNBUFFERED="1", NO_COLOR="1", PYTHONPATH=str(REPO_ROOT))
    env.update(extra)
    return env


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


# ── metrics ──────────────────────────────────────────────────────────────────

class Metrics:
    def __init__(self):
        self.req = Counter()                     # (phase, endpoint, status) -> n
        self.lat = defaultdict(list)             # endpoint -> [s]
        self.pdf_bytes = Counter()               # phase -> bytes
        self.resp_bytes = Counter()              # endpoint -> response body bytes
        self.slide_lat = defaultdict(list)       # phase -> [s]
        self.slide_events = []                   # [(phase, page, expected, delivered)]
        self.emoji = Counter()                   # (phase, status) -> n
        self.screen = Counter()                  # phase -> display_emoji frames
        self.screen_times: list[float] = []
        self.log_lines = Counter()               # (proc, phase) -> stdout lines
        self.join_time: list[float] = []         # page GET -> first slide on screen
        self.reconnect_time: list[float] = []    # WS drop -> WS open + state 200
        self.ws_connect = Counter()              # phase -> ok / error
        self.ws_closed_by_server = Counter()     # close code -> n
        self.phases: list[tuple[str, float, float]] = []

    def record(self, ep: str, status, dt: float | None):
        self.req[(PHASE["name"], ep, status)] += 1
        if dt is not None:
            self.lat[ep].append(dt)


class ProcSampler(threading.Thread):
    """psutil sampling every 0.5 s on a thread, so a busy event loop cannot skew it."""

    def __init__(self, procs: dict, interval: float = 0.5):
        super().__init__(daemon=True)
        import psutil
        self.psutil = psutil
        self.procs = {name: psutil.Process(pid) for name, pid in procs.items()}
        self.interval = interval
        self.samples = []            # (t, phase, name, cpu%, rss)
        self.sys_samples = []        # (t, phase, whole box core-%, core-% of processes outside this test)
        self.cores = psutil.cpu_count() or 1
        self.cpu_marks = []          # (phase starting, {name: cpu_seconds}, t)
        self._stop = threading.Event()
        for p in self.procs.values():
            p.cpu_percent(None)
        psutil.cpu_percent(None)

    def cpu_seconds(self) -> dict:
        out = {}
        for name, p in self.procs.items():
            try:
                t = p.cpu_times()
                out[name] = t.user + t.system
            except self.psutil.Error:
                out[name] = float("nan")
        return out

    def mark(self, phase: str) -> None:
        self.cpu_marks.append((phase, self.cpu_seconds(), now()))

    def run(self):
        while not self._stop.wait(self.interval):
            t, ph = now(), PHASE["name"]
            mine = 0.0
            for name, p in self.procs.items():
                try:
                    cpu = p.cpu_percent(None)
                    mine += cpu
                    self.samples.append((t, ph, name, cpu, p.memory_info().rss))
                except self.psutil.Error:
                    pass
            box = self.psutil.cpu_percent(None) * self.cores
            self.sys_samples.append((t, ph, box, max(0.0, box - mine)))

    def stop(self):
        self._stop.set()


def set_phase(name: str, m: Metrics, sampler: ProcSampler | None) -> None:
    t = now()
    if m.phases:
        prev, start, _ = m.phases[-1]
        m.phases[-1] = (prev, start, t)
    m.phases.append((name, t, t))
    PHASE["name"] = name
    if sampler:
        sampler.mark(name)
    print(f"  [{time.strftime('%H:%M:%S')}] phase → {name}", flush=True)


# ── local stack ──────────────────────────────────────────────────────────────

def pump_lines(proc: subprocess.Popen, name: str, log_path: Path, m: Metrics) -> threading.Thread:
    """Copy a child's stdout to a log file, counting lines per phase."""
    def run():
        with log_path.open("w", encoding="utf-8", errors="replace") as f:
            for raw in iter(proc.stdout.readline, b""):
                m.log_lines[(name, PHASE["name"])] += 1
                f.write(raw.decode("utf-8", errors="replace"))
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class Stack:
    def __init__(self, deck: Path, work: Path, m: Metrics):
        self.work = work
        self.m = m
        self.rport, self.dport, self.bport, self.drive_port = (free_port() for _ in range(4))
        self.connect_ip = primary_ip()
        self.base = f"http://{self.connect_ip}:{self.rport}"
        self.ws_base = f"ws://{self.connect_ip}:{self.rport}"
        self.local = f"http://127.0.0.1:{self.rport}"
        self.daemon_base = f"http://127.0.0.1:{self.dport}"
        self.procs: dict[str, subprocess.Popen] = {}

        for d in ("sessions", "transcriptions", "fixtures", "pptx"):
            (work / d).mkdir(parents=True, exist_ok=True)
        fixture = work / "fixtures" / f"{DECK_SLUG}.pdf"
        if not fixture.exists():
            fixture.symlink_to(deck.resolve())
        (work / "pptx" / DECK_PPTX).touch()
        self.catalog = work / "catalog.json"
        self.catalog.write_text(json.dumps({"decks": [{
            "title": DECK_TITLE,
            "slug": DECK_SLUG,
            "source": str(work / "pptx" / DECK_PPTX),
            "target_pdf": f"{DECK_SLUG}.pdf",
            "drive_export_url": f"http://127.0.0.1:{self.drive_port}/presentation/d/{DECK_SLUG}/export/pdf",
            "group": "Talk",
        }]}, indent=2))

    def _spawn(self, name: str, args: list[str], env: dict) -> subprocess.Popen:
        p = subprocess.Popen(args, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        self.procs[name] = p
        pump_lines(p, name, self.work / f"{name}.log", self.m)
        return p

    def start(self, private_cache: bool, uvicorn_args: list[str]):
        py = sys.executable
        railway_cmd = [py, "-m", "uvicorn", "railway.app:app", "--host", "0.0.0.0",
                       "--port", str(self.rport), "--ws-ping-interval", "20",
                       "--ws-ping-timeout", "60", *uvicorn_args]
        if private_cache:
            # Railway caches PDFs in the hardcoded /tmp/slides-cache. Give this
            # instance its own (tmpfs in a private mount namespace), so another local
            # Railway or test can never rewrite or delete the file our phones read.
            Path("/tmp/slides-cache").mkdir(parents=True, exist_ok=True)
            railway_cmd = ["unshare", "--mount", "--propagation", "private", "sh", "-c",
                           'mount -t tmpfs tmpfs /tmp/slides-cache && exec "$@"', "sh", *railway_cmd]
        self._spawn("drive", [py, "tests/docker/mock_drive_server.py"], clean_env(
            FIXTURE_PDF_DIR=str(self.work / "fixtures"), MOCK_DRIVE_PORT=str(self.drive_port),
            OTEL_SDK_DISABLED="true"))
        self._spawn("railway", railway_cmd,
                    clean_env(HOST_USERNAME=HOST_USER, HOST_PASSWORD=HOST_PASS,
                              TRAINING_ASSISTANTS_SECRETS_FILE=str(self.work / "no-secrets.env")))

    def start_daemon(self):
        # Same as `python -m daemon`, except its single-instance lock file lives in
        # the work dir (daemon/lock.py hardcodes /tmp/training_daemon.lock).
        boot = ("import sys, runpy; from pathlib import Path; import daemon.lock as L; "
                "L._LOCK_FILE = Path(sys.argv[1]); sys.argv = ['daemon']; "
                "runpy.run_module('daemon', run_name='__main__', alter_sys=True)")
        self._spawn("daemon", [sys.executable, "-c", boot, str(self.work / "daemon.lock")], clean_env(
            HOST_USERNAME=HOST_USER, HOST_PASSWORD=HOST_PASS,
            ANTHROPIC_API_KEY="sk-test-dummy-key-for-load-testing",
            SESSIONS_FOLDER=str(self.work / "sessions"),
            TRANSCRIPTION_FOLDER=str(self.work / "transcriptions"),
            WORKSHOP_SERVER_URL=self.local,
            DAEMON_ADAPTER="stub", LLM_ADAPTER="stub", TRANSCRIPT_LLM_CLEAN="0",
            DAEMON_HOST_PORT=str(self.dport), DAEMON_OPEN_BROWSER="0",
            WS_SERVER_PORT=str(self.bport),
            DAEMON_WS_RECONNECT_INTERVAL_SECONDS="0.5",
            PPTX_CATALOG_FILE=str(self.catalog), PPTX_WATCH_DIR=str(self.work / "pptx"),
            TRAINING_ASSISTANTS_SECRETS_FILE=str(self.work / "no-secrets.env"),
            GITHUB_API_BASE="http://127.0.0.1:9", GITHUB_BLOB_BASE="http://127.0.0.1:9",
            MATERIALS_FOLDER=str(self.work / "no-materials"),
        ))

    def stop(self):
        for name in ("daemon", "railway", "drive"):
            p = self.procs.get(name)
            if p and p.poll() is None:
                p.terminate()
        for p in self.procs.values():
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


async def wait_http(client, url: str, ok=lambda r: r.status_code == 200, timeout=40.0, what=""):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            r = await client.get(url)
            last = r.status_code
            if ok(r):
                return r
        except Exception as e:  # noqa: BLE001 - polling until up
            last = type(e).__name__
        await asyncio.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {what or url} (last: {last})")


# ── mock add-on bridge (the trainer's screen) ────────────────────────────────

class Bridge:
    def __init__(self, port: int, m: Metrics):
        self.port = port
        self.m = m
        self.ws = None
        self.connected = asyncio.Event()
        self.sent_at: dict[int, float] = {}
        self.other = Counter()
        self.server = None

    async def start(self):
        from websockets.asyncio.server import serve
        self.server = await serve(self._handle, "127.0.0.1", self.port)

    async def _handle(self, ws):
        self.ws = ws
        self.connected.set()
        try:
            async for raw in ws:
                try:
                    t = json.loads(raw).get("type")
                except (ValueError, AttributeError):
                    continue
                if t == "display_emoji":
                    self.m.screen[PHASE["name"]] += 1
                    self.m.screen_times.append(now())
                else:
                    self.other[t] += 1
        except Exception:  # noqa: BLE001 - daemon went away
            pass
        finally:
            if self.ws is ws:
                self.ws = None
                self.connected.clear()

    async def present(self, page: int):
        self.sent_at[page] = now()
        await self.ws.send(json.dumps({"type": "slide_presenting_now", "deck": DECK_PPTX,
                                       "slide": page, "presenting": True}))

    async def close(self):
        if self.server:
            self.server.close()


# ── simulated phone ──────────────────────────────────────────────────────────

class Ctx:
    def __init__(self, stack: Stack, m: Metrics, bridge: Bridge, sid: str, n_chunks: int):
        self.stack, self.m, self.bridge, self.sid = stack, m, bridge, sid
        # Shared by every phone's client: building an SSL context per client would
        # reload the CA bundle 500 times (the URLs are plain http anyway).
        self.ssl_ctx = ssl.create_default_context()
        self.n_chunks = n_chunks
        self.stopping = False
        last = n_chunks - 1
        spread = {round(i * last / (INITIAL_CHUNKS - 3)) for i in range(INITIAL_CHUNKS - 2)}
        self.initial_chunks = sorted({last, last - 1, 0} | spread)

    async def req(self, http, ep: str, method: str, path: str, headers: dict, **kw):
        t = now()
        try:
            r = await http.request(method, self.stack.base + path, headers=headers, **kw)
        except Exception as e:  # noqa: BLE001 - every failure is a data point
            self.m.record(ep, f"ERR:{type(e).__name__}", None)
            return None
        dt = now() - t
        self.m.record(ep, r.status_code, dt)
        self.m.resp_bytes[ep] += len(r.content)
        if ep == "pdf_range":
            self.m.pdf_bytes[PHASE["name"]] += len(r.content)
        return r


class Phone:
    def __init__(self, idx: int, ctx: Ctx):
        self.idx = idx
        self.ctx = ctx
        self.uuid = str(uuid.uuid4())
        self.hdr = {"X-Forwarded-For": NAT_IP, "X-Participant-ID": self.uuid}
        self.pdf_hdr = {"X-Forwarded-For": NAT_IP}
        self.registered = False
        self.ws = None
        self.ws_open = False
        self.deck_opened = False
        self.slug = DECK_SLUG
        self.pages: set[int] = set()
        self.lock = asyncio.Lock()
        self.ready = asyncio.Event()      # first slide on screen
        self.emoji_sent = 0
        self.dropped_at: float | None = None
        self.reader: asyncio.Task | None = None
        self.bg: set[asyncio.Task] = set()
        # One client per phone, like one browser: its own cookies and at most 6
        # connections to the host. (One shared client with N connections made the
        # generator quadratic: httpcore scans its whole pool on every request.)
        import httpx
        self.http = httpx.AsyncClient(
            trust_env=False, timeout=40, verify=ctx.ssl_ctx,
            # keepalive_expiry < uvicorn's 5 s keep-alive timeout: never reuse a socket
            # the server is closing (a browser silently retries that; httpx would not).
            limits=httpx.Limits(max_connections=6, max_keepalive_connections=6, keepalive_expiry=4))

    def req(self, ep: str, method: str, path: str, headers: dict, **kw):
        return self.ctx.req(self.http, ep, method, path, headers, **kw)

    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self.bg.add(t)
        t.add_done_callback(self.bg.discard)

    async def join(self):
        c, sid = self.ctx, self.ctx.sid
        t0 = now()
        for attempt in range(6):  # a 429 on the page: the person hits reload after ~1 s
            r = await self.req("page", "GET", f"/{sid}/", self.pdf_hdr)
            if r is not None and r.status_code == 200:
                break
            await asyncio.sleep(1 + random.random())
        else:
            return
        for asset in ("/static/emoji-float.js", "/static/tooltip.js", "/static/favicon-new.svg"):
            await self.req("static", "GET", asset, self.pdf_hdr)
        await self.ensure_identity()
        self._spawn(self.ws_loop())
        await self.sync_state()
        await self.ready.wait()
        c.m.join_time.append(now() - t0)

    async def ensure_identity(self):
        if self.registered:
            return
        r = await self.req("register", "POST", f"/{self.ctx.sid}/api/participant/register",
                               self.hdr, json={})
        self.registered = r is not None and r.status_code == 200

    async def sync_state(self, attempt: int = 0) -> bool:
        while not self.ctx.stopping:
            r = await self.req("state", "GET", f"/{self.ctx.sid}/api/participant/state", self.hdr)
            if r is not None and r.status_code == 200:
                st = r.json()
                sc = st.get("slides_current") or (
                    {"slug": st["talk_presentation_slug"], "page": 1} if st.get("talk_presentation_slug") else None)
                if sc:
                    self._spawn(self.show(sc["slug"], int(sc.get("page") or 1)))
                return True
            await asyncio.sleep(backoff(attempt))
            attempt += 1
        return False

    async def show(self, slug: str, page: int):
        async with self.lock:
            if not self.deck_opened:
                await self.open_deck(slug)
            if page not in self.pages:
                self.pages.add(page)
                n = self.ctx.n_chunks
                first = min(n - 1, int((page - 1) / max(1, self.ctx.n_pages) * n))
                for idx in range(first, min(n, first + random.choice((1, 2)))):
                    await self.range_get(idx)
            self.ready.set()

    async def open_deck(self, slug: str):
        c, sid = self.ctx, self.ctx.sid
        self.slug = slug
        for attempt in range(10):
            r = await self.req("check", "GET", f"/{sid}/api/slides/check/{slug}", self.hdr, timeout=40.0)
            if r is not None and r.status_code in (200, 404):
                break
            await asyncio.sleep(1 + random.random() * min(15, 2 ** attempt))  # talk.html retryDelay
        url = c.stack.base + f"/{sid}/api/slides/download/{slug}"
        # pdf.js: a plain GET first; with disableStream it cancels the body once the
        # headers say ranges are supported.
        t = now()
        try:
            async with self.http.stream("GET", url, headers=self.pdf_hdr) as r:
                c.m.record("pdf_open_get", r.status_code, now() - t)
        except Exception as e:  # noqa: BLE001
            c.m.record("pdf_open_get", f"ERR:{type(e).__name__}", None)
        for idx in c.initial_chunks:
            await self.range_get(idx)
        self.deck_opened = True

    async def range_get(self, idx: int):
        start = idx * RANGE_CHUNK
        end = min(self.ctx.pdf_size, start + RANGE_CHUNK) - 1
        await self.req("pdf_range", "GET", f"/{self.ctx.sid}/api/slides/download/{self.slug}",
                           {**self.pdf_hdr, "Range": f"bytes={start}-{end}"})

    async def ws_loop(self):
        from websockets.asyncio.client import connect
        c = self.ctx
        attempt = 0
        reconnected = False
        while not c.stopping:
            try:
                ws = await connect(f"{c.stack.ws_base}/ws/{c.sid}/{self.uuid}",
                                   additional_headers={"X-Forwarded-For": NAT_IP},
                                   proxy=None, max_size=None, open_timeout=30,
                                   ping_interval=None)  # permessage-deflate on, like browsers
            except Exception as e:  # noqa: BLE001
                c.m.ws_connect[(PHASE["name"], f"ERR:{type(e).__name__}")] += 1
                await asyncio.sleep(backoff(attempt))
                attempt += 1
                continue
            c.m.ws_connect[(PHASE["name"], "ok")] += 1
            self.ws, self.ws_open, attempt = ws, True, 0
            if reconnected:  # broadcasts sent while away are lost: catch up from /state
                self._spawn(self.after_reconnect())
            try:
                async for raw in ws:
                    if SLIDE_MARK in raw:
                        t = now()
                        msg = json.loads(raw)
                        if msg.get("type") == SLIDE_MARK:
                            sc = msg.get("current_slide") or {}
                            page = int(sc.get("page") or 1)
                            sent = c.bridge.sent_at.get(page)
                            if sent is not None:
                                c.m.slide_lat[PHASE["name"]].append(t - sent)
                            c.delivered[page] = c.delivered.get(page, 0) + 1
                            self._spawn(self.show(sc.get("slug") or DECK_SLUG, page))
            except Exception:  # noqa: BLE001 - dropped / reset
                pass
            self.ws_open = False
            code = ws.close_code
            if code is not None and self.dropped_at is None:
                c.m.ws_closed_by_server[code] += 1
            if code == 1008:
                return
            reconnected = True
            if c.stopping:
                return
            await asyncio.sleep(backoff(attempt))
            attempt += 1

    async def after_reconnect(self):
        await self.ensure_identity()
        ok = await self.sync_state()
        if ok and self.dropped_at is not None:
            self.ctx.m.reconnect_time.append(now() - self.dropped_at)
            self.dropped_at = None

    def drop(self):
        if self.ws is not None and self.ws_open:
            self.dropped_at = now()
            self.ws.transport.abort()   # network loss: RST, no close frame

    async def emoji(self):
        r = await self.req("emoji", "POST", f"/{self.ctx.sid}/api/participant/emoji/reaction",
                               self.hdr, json={"emoji": random.choice(TALK_EMOJIS)})
        self.ctx.m.emoji[(PHASE["name"], r.status_code if r is not None else "ERR")] += 1

    async def close(self):
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass
        await self.http.aclose()


def backoff(attempt: int) -> float:
    """talk.html _backoffDelay: 250 ms + full jitter up to min(15 s, 500 ms * 2^n)."""
    return (250 + random.random() * min(15000, 500 * 2 ** attempt)) / 1000


# ── one run ──────────────────────────────────────────────────────────────────

async def run_one(n: int, args, deck: Path, work: Path) -> dict:
    import httpx
    m = Metrics()
    PHASE["name"] = "setup"
    stack = Stack(deck, work, m)
    bridge = Bridge(stack.bport, m)
    await bridge.start()
    stack.start(private_cache=args.private_slides_cache, uvicorn_args=args.uvicorn_arg)
    auth = {"Authorization": "Basic " + base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()}
    sampler = None
    phones: list[Phone] = []
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=10) as admin:
            await wait_http(admin, f"{stack.local}/api/status", what="railway")
            await wait_http(admin, f"http://127.0.0.1:{stack.drive_port}/mock-drive/stats", what="mock drive")
            stack.start_daemon()
            await wait_http(admin, f"{stack.daemon_base}/api/session/active", what="daemon")
            r = await admin.post(f"{stack.daemon_base}/api/session/create", headers=auth,
                                 json={"name": f"Load talk {n}", "type": "talk"})
            r.raise_for_status()
            sid = r.json()["session_id"]
            await wait_http(admin, f"{stack.local}/{sid}/api/status",
                            ok=lambda r: r.status_code == 200 and r.json().get("session_active"),
                            what="session active on Railway")
            await wait_http(admin, f"{stack.daemon_base}/api/session/active",
                            ok=lambda r: r.json().get("session_id") == sid, what="daemon session")
            await asyncio.wait_for(bridge.connected.wait(), 30)

            sampler = ProcSampler({"railway": stack.procs["railway"].pid,
                                   "daemon": stack.procs["daemon"].pid,
                                   "generator": os.getpid(),
                                   "drive": stack.procs["drive"].pid})
            sampler.start()
            ctx = Ctx(stack, m, bridge, sid, n_chunks=(deck.stat().st_size + RANGE_CHUNK - 1) // RANGE_CHUNK)
            ctx.pdf_size = deck.stat().st_size
            ctx.n_pages = args.pages
            ctx.delivered = {}
            phones = [Phone(i, ctx) for i in range(n)]

            # The trainer opens the deck on slide 1 before the doors open.
            await bridge.present(1)
            await asyncio.sleep(2.5)
            set_phase("idle", m, sampler)
            await asyncio.sleep(3)

            # ── (a) join storm ──
            set_phase("join", m, sampler)
            offsets = sorted(random.uniform(0, args.join_window) for _ in phones)
            t_join = now()

            async def join_at(p: Phone, off: float):
                await asyncio.sleep(max(0.0, t_join + off - now()))
                await p.join()

            join_tasks = [asyncio.create_task(join_at(p, off)) for p, off in zip(phones, offsets)]
            done, pending = await asyncio.wait(join_tasks, timeout=args.join_window + args.join_grace)
            joined = sum(1 for p in phones if p.ready.is_set())
            for t in pending:
                t.cancel()
            join_wall = now() - t_join
            print(f"  joined {joined}/{n} in {join_wall:.1f} s", flush=True)

            # ── (b) steady talk ──
            set_phase("steady", m, sampler)
            pages = [3, 7, 12, 18, 25, 33, 41, 56, 72, 90, 104, 110][:args.slides]
            joke_at = {len(pages) // 3, (2 * len(pages)) // 3}
            trickle_stop = asyncio.Event()

            async def trickle():
                rate = max(1.0, 0.01 * n)
                while not trickle_stop.is_set():
                    await asyncio.sleep(random.expovariate(rate))
                    p = random.choice(phones)
                    if p.ready.is_set() and p.emoji_sent < 12:
                        p.emoji_sent += 1
                        asyncio.create_task(p.emoji())

            async def joke():
                async def one(p: Phone):
                    for _ in range(random.randint(1, 3)):
                        await asyncio.sleep(random.uniform(0, 2.0))
                        await p.emoji()
                ready = [p for p in phones if p.ready.is_set()]
                crowd = random.sample(ready, k=min(len(ready), int(0.4 * len(ready))))
                await asyncio.gather(*(one(p) for p in crowd))

            trickle_task = asyncio.create_task(trickle())
            joke_tasks = []
            for i, page in enumerate(pages):
                expected = sum(1 for p in phones if p.ws_open)
                ctx.delivered[page] = 0
                await bridge.present(page)
                if i in joke_at:
                    await asyncio.sleep(1.0)
                    joke_tasks.append(asyncio.create_task(joke()))
                    await asyncio.sleep(args.slide_interval - 1.0)
                else:
                    await asyncio.sleep(args.slide_interval)
                m.slide_events.append(("steady", page, expected, ctx.delivered.get(page, 0)))
            trickle_stop.set()
            await asyncio.gather(*joke_tasks, trickle_task, return_exceptions=True)
            await asyncio.sleep(2)

            # ── (c) reconnect wave ──
            set_phase("reconnect", m, sampler)
            open_now = [p for p in phones if p.ws_open]
            victims = random.sample(open_now, k=min(len(open_now), int(0.2 * len(open_now))))
            for p in victims:
                p.drop()
            deadline = now() + 30
            while now() < deadline and any(p.dropped_at is not None for p in victims):
                await asyncio.sleep(0.2)
            back = sum(1 for p in victims if p.dropped_at is None)
            print(f"  reconnect wave: {back}/{len(victims)} back with state", flush=True)
            await asyncio.sleep(1)
            page = 111
            expected = sum(1 for p in phones if p.ws_open)
            ctx.delivered[page] = 0
            await bridge.present(page)
            await asyncio.sleep(args.slide_interval)
            m.slide_events.append(("reconnect", page, expected, ctx.delivered.get(page, 0)))

            set_phase("end", m, sampler)
            ctx.stopping = True
            sampler.stop()
            await asyncio.gather(*(p.close() for p in phones), return_exceptions=True)
            for p in phones:
                for t in list(p.bg):
                    t.cancel()
            await asyncio.sleep(0.5)
            return summarize(n, m, sampler, joined, join_wall, len(victims), back)
    finally:
        if sampler:
            sampler.stop()
        await bridge.close()
        stack.stop()


# ── reporting ────────────────────────────────────────────────────────────────

REPORT_PHASES = ["idle", "join", "steady", "reconnect"]


def summarize(n, m: Metrics, sampler: ProcSampler, joined, join_wall, victims, back) -> dict:
    phases = {name: (start, end) for name, start, end in m.phases}
    marks = sampler.cpu_marks
    cpu_s = {}
    for i, (ph, secs, t) in enumerate(marks[:-1]):
        nxt_secs, nxt_t = marks[i + 1][1], marks[i + 1][2]
        cpu_s[ph] = {k: nxt_secs[k] - secs[k] for k in secs}
        cpu_s[ph]["_dur"] = nxt_t - t
    procs = {}
    for name in ("railway", "daemon", "generator", "drive"):
        s = [x for x in sampler.samples if x[2] == name and x[1] in REPORT_PHASES]
        cpus = [x[3] for x in s]
        rss = [x[4] for x in s]
        procs[name] = {
            "cpu_avg": sum(cpus) / len(cpus) if cpus else float("nan"),
            "cpu_peak": max(cpus) if cpus else float("nan"),
            "rss_start_mb": rss[0] / 2**20 if rss else float("nan"),
            "rss_peak_mb": max(rss) / 2**20 if rss else float("nan"),
            "rss_end_mb": rss[-1] / 2**20 if rss else float("nan"),
            "per_phase": {ph: {
                "cpu_s": cpu_s.get(ph, {}).get(name, float("nan")),
                "avg_pct": 100 * cpu_s.get(ph, {}).get(name, float("nan")) / max(1e-9, cpu_s.get(ph, {}).get("_dur", 1)),
                "peak_pct": max([x[3] for x in s if x[1] == ph] or [float("nan")]),
            } for ph in REPORT_PHASES},
        }
    def _avg(v):
        return sum(v) / len(v) if v else float("nan")
    sys_cpu = {ph: max([x[2] for x in sampler.sys_samples if x[1] == ph] or [float("nan")]) for ph in REPORT_PHASES}
    sys_avg = {ph: _avg([x[2] for x in sampler.sys_samples if x[1] == ph]) for ph in REPORT_PHASES}
    foreign_avg = {ph: _avg([x[3] for x in sampler.sys_samples if x[1] == ph]) for ph in REPORT_PHASES}
    foreign_peak = max([x[3] for x in sampler.sys_samples if x[1] in REPORT_PHASES] or [float("nan")])
    by_ep = defaultdict(Counter)
    by_ep_phase = defaultdict(Counter)
    for (ph, ep, st), k in m.req.items():
        by_ep[ep][str(st)] += k
        by_ep_phase[(ep, ph)][str(st)] += k
    emoji = defaultdict(Counter)
    for (ph, st), k in m.emoji.items():
        emoji[ph][str(st)] += k
    steady = phases.get("steady", (0, 0))
    burst = 20.0
    rate = 8.0
    return {
        "n": n, "joined": joined, "join_wall_s": join_wall,
        "phase_durations": {ph: phases[ph][1] - phases[ph][0] for ph in phases if ph in REPORT_PHASES},
        "procs": procs, "sys_cpu_peak": sys_cpu, "sys_cpu_avg": sys_avg,
        "foreign_cpu_avg": foreign_avg, "foreign_cpu_peak": foreign_peak,
        "requests": {ep: dict(c) for ep, c in by_ep.items()},
        "requests_by_phase": {f"{ep}|{ph}": dict(c) for (ep, ph), c in by_ep_phase.items()},
        "resp_bytes": dict(m.resp_bytes),
        "latency": {ep: {"p50": pct(v, 50), "p95": pct(v, 95), "max": max(v), "n": len(v)}
                    for ep, v in m.lat.items() if v},
        "join_time": {"p50": pct(m.join_time, 50), "p95": pct(m.join_time, 95),
                      "max": max(m.join_time) if m.join_time else float("nan")},
        "slide_lat": {ph: {"p50": pct(v, 50), "p95": pct(v, 95), "max": max(v), "n": len(v)}
                      for ph, v in m.slide_lat.items() if v},
        "slide_events": m.slide_events,
        "pdf_bytes": dict(m.pdf_bytes),
        "emoji": {ph: dict(c) for ph, c in emoji.items()},
        "screen": dict(m.screen),
        "screen_cap_steady": burst + rate * (steady[1] - steady[0]),
        "log_lines": {f"{p}|{ph}": k for (p, ph), k in m.log_lines.items()},
        "reconnect": {"victims": victims, "back": back,
                      "p50": pct(m.reconnect_time, 50), "p95": pct(m.reconnect_time, 95),
                      "max": max(m.reconnect_time) if m.reconnect_time else float("nan")},
        "ws_connect": {f"{ph}|{st}": k for (ph, st), k in m.ws_connect.items()},
        "ws_closed_by_server": dict(m.ws_closed_by_server),
    }


def fmt(x, d=0):
    return "n/a" if x != x else f"{x:.{d}f}"


def markdown(results: list[dict], meta: dict) -> str:
    L = []
    L.append("# Talk full-stack load test\n")
    L.append(f"- Machine: **{meta['cpu']}**, {meta['cores']} cores, {meta['mem_gb']:.0f} GB RAM "
             f"(Linux container; Railway, daemon and the load generator share these cores — "
             f"the trainer's Apple Silicon Mac is likely faster per core)")
    if meta.get("uvicorn_args"):
        L.append(f"- Extra Railway uvicorn flags: `{meta['uvicorn_args']}`")
    L.append(f"- Commit `{meta['commit']}`; generator event loop: {meta['loop']}; deck {meta['deck_mb']:.1f} MB, "
             f"{meta['pages']} pages, {meta['chunks']} × 128 KiB chunks")
    L.append(f"- Phones join within {meta['join_window']:.0f} s from ONE IP (X-Forwarded-For {NAT_IP}, "
             f"non-loopback peer); {meta['slides']} slide changes {meta['slide_interval']:.0f} s apart; "
             f"2 jokes (40% of phones × 1–3 reactions in 2 s) + 1%/s trickle; 20% WS drop wave\n")

    L.append("## CPU and memory (psutil, 0.5 s samples)\n")
    L.append("| N | process | CPU-s idle / join / steady / reconnect | avg CPU% join / steady / reconnect | peak CPU% | RSS start → peak → end (MB) |")
    L.append("|---|---|---|---|---|---|")
    for r in results:
        for name in ("railway", "daemon", "generator"):
            p = r["procs"][name]
            pp = p["per_phase"]
            L.append(f"| {r['n']} | {name} | " + " / ".join(fmt(pp[ph]["cpu_s"], 1) for ph in REPORT_PHASES)
                     + " | " + " / ".join(fmt(pp[ph]["avg_pct"]) for ph in REPORT_PHASES[1:])
                     + f" | {fmt(p['cpu_peak'])} | {fmt(p['rss_start_mb'])} → {fmt(p['rss_peak_mb'])} → {fmt(p['rss_end_mb'])} |")
        L.append(f"| {r['n']} | whole box (of {meta['cores']*100}%) | | " + " / ".join(fmt(r['sys_cpu_avg'][ph]) for ph in REPORT_PHASES[1:])
                 + " | " + fmt(max([v for v in r['sys_cpu_peak'].values() if v == v] or [float('nan')])) + " | |")
        L.append(f"| {r['n']} | other processes (not this test) | | " + " / ".join(fmt(r['foreign_cpu_avg'][ph]) for ph in REPORT_PHASES[1:])
                 + f" | {fmt(r['foreign_cpu_peak'])} | |")
    L.append("\nPhase durations (s): " + "; ".join(
        f"N={r['n']}: " + ", ".join(f"{ph} {fmt(d, 1)}" for ph, d in r["phase_durations"].items()) for r in results) + "\n")

    L.append("## Requests\n")
    L.append("| N | endpoint | statuses | p50 / p95 / max (ms) | avg body (KB) |")
    L.append("|---|---|---|---|---|")
    order = ["page", "static", "register", "state", "check", "pdf_open_get", "pdf_range", "emoji"]
    for r in results:
        for ep in order + sorted(set(r["requests"]) - set(order)):
            if ep not in r["requests"]:
                continue
            st = ", ".join(f"{k}: {v}" for k, v in sorted(r["requests"][ep].items()))
            lat = r["latency"].get(ep)
            l3 = f"{lat['p50']*1000:.0f} / {lat['p95']*1000:.0f} / {lat['max']*1000:.0f}" if lat else "n/a"
            cnt = sum(r["requests"][ep].values())
            body = r.get("resp_bytes", {}).get(ep)
            kb = fmt(body / cnt / 1024, 1) if body and cnt else ""
            L.append(f"| {r['n']} | {ep} | {st} | {l3} | {kb} |")
    L.append("")
    L.append("| N | joined | join: page → first slide on screen p50 / p95 / max (s) | PDF bytes served (MB) join / steady / reconnect | WS connects (ok / err) |")
    L.append("|---|---|---|---|---|")
    for r in results:
        jt = r["join_time"]
        pb = r["pdf_bytes"]
        ok = sum(v for k, v in r["ws_connect"].items() if k.endswith("|ok"))
        err = sum(v for k, v in r["ws_connect"].items() if not k.endswith("|ok"))
        L.append(f"| {r['n']} | {r['joined']}/{r['n']} ({fmt(r['join_wall_s'], 1)} s) | {fmt(jt['p50'], 2)} / {fmt(jt['p95'], 2)} / {fmt(jt['max'], 2)} | "
                 + " / ".join(fmt(pb.get(ph, 0) / 2**20, 0) for ph in ("join", "steady", "reconnect"))
                 + f" | {ok} / {err} |")

    L.append("\n## Slide follow (mock bridge → daemon → Railway → phone WS)\n")
    L.append("| N | phase | delivery p50 / p95 / max (ms) | deliveries | per change: delivered / open WS |")
    L.append("|---|---|---|---|---|")
    for r in results:
        for ph in ("steady", "reconnect"):
            s = r["slide_lat"].get(ph)
            ev = [e for e in r["slide_events"] if e[0] == ph]
            per = " ".join(f"{d}/{x}" for _, _, x, d in ev)
            l3 = f"{s['p50']*1000:.0f} / {s['p95']*1000:.0f} / {s['max']*1000:.0f}" if s else "n/a"
            L.append(f"| {r['n']} | {ph} | {l3} | {s['n'] if s else 0} | {per} |")
    L.append("")
    L.append("| N | reconnect wave: dropped | back (WS + state 200) | drop → back p50 / p95 / max (s) |")
    L.append("|---|---|---|---|")
    for r in results:
        rc = r["reconnect"]
        L.append(f"| {r['n']} | {rc['victims']} | {rc['back']} | {fmt(rc['p50'], 2)} / {fmt(rc['p95'], 2)} / {fmt(rc['max'], 2)} |")

    L.append("\n## Emoji → screen\n")
    L.append("| N | phase | reactions sent | 204 | 429 | other | display_emoji on screen | cap (20 + 8/s × steady) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        for ph in ("steady", "reconnect"):
            e = r["emoji"].get(ph, {})
            sent = sum(e.values())
            if not sent and not r["screen"].get(ph):
                continue
            other = sent - e.get("204", 0) - e.get("429", 0)
            cap = fmt(r["screen_cap_steady"]) if ph == "steady" else ""
            L.append(f"| {r['n']} | {ph} | {sent} | {e.get('204', 0)} | {e.get('429', 0)} | {other} | {r['screen'].get(ph, 0)} | {cap} |")

    L.append("\n## Log volume (stdout lines)\n")
    L.append("| N | process | idle | join | steady | reconnect |")
    L.append("|---|---|---|---|---|---|")
    for r in results:
        for proc in ("daemon", "railway"):
            L.append(f"| {r['n']} | {proc} | " + " | ".join(str(r["log_lines"].get(f"{proc}|{ph}", 0)) for ph in REPORT_PHASES) + " |")
    return "\n".join(L) + "\n"


# ── main ─────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="talk_fullstack_load.py",
        description=__doc__.split("\n\n")[0],
        epilog=__doc__.split("\n\n", 1)[1],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", type=Path, required=True,
                    help=f"the PDF served as the '{DECK_TITLE}' deck (mock Google Drive export)")
    ap.add_argument("--pages", type=int, default=112, help="page count of --deck (default 112)")
    ap.add_argument("--participants", "-n", type=int, nargs="+", default=[100, 300, 500],
                    help="room sizes to run, each on a fresh stack (default: 100 300 500)")
    ap.add_argument("--join-window", type=float, default=30.0, help="phones join within this many s (default 30)")
    ap.add_argument("--join-grace", type=float, default=90.0,
                    help="extra s to wait for the last phone to see its first slide (default 90)")
    ap.add_argument("--slides", type=int, default=10, help="slide changes in the steady phase (default 10)")
    ap.add_argument("--slide-interval", type=float, default=4.0, help="s between slide changes (default 4)")
    ap.add_argument("--work-dir", type=Path, default=None, help="logs + temp state (default: new temp dir)")
    ap.add_argument("--out-json", type=Path, default=None, help="write raw results as JSON")
    ap.add_argument("--out-md", type=Path, default=None, help="write the markdown report")
    ap.add_argument("--no-uvloop", action="store_true", help="use the default asyncio loop for the generator")
    ap.add_argument("--uvicorn-arg", action="append", default=[],
                    help="extra uvicorn flag for Railway, e.g. --uvicorn-arg=--no-access-log (repeatable)")
    ap.add_argument("--private-slides-cache", action=argparse.BooleanOptionalAction,
                    default=sys.platform.startswith("linux") and os.geteuid() == 0,
                    help="run Railway in a private mount namespace with its own tmpfs "
                         "/tmp/slides-cache (Linux, root; default: on when possible)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        import httpx  # noqa: F401
        import psutil  # noqa: F401
        import websockets  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"missing dependency ({e}); run it with: uv run --extra dev --extra daemon "
                         "--extra telemetry --with psutil --with uvloop python tests/load/talk_fullstack_load.py ...")
    if not args.deck.is_file():
        raise SystemExit(f"--deck not found: {args.deck}")
    raise_fd_limit()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # run the finally blocks: stop the stack
    loop_name = "asyncio"
    if not args.no_uvloop:
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            loop_name = f"uvloop {uvloop.__version__}"
        except ImportError:
            pass
    work_root = args.work_dir or Path(tempfile.mkdtemp(prefix="talk-load-"))
    import psutil
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                            capture_output=True, text=True).stdout.strip()
    meta = {"uvicorn_args": " ".join(args.uvicorn_arg), "cpu": cpu_model(), "cores": psutil.cpu_count(), "mem_gb": psutil.virtual_memory().total / 2**30,
            "commit": commit, "loop": loop_name, "deck_mb": args.deck.stat().st_size / 2**20,
            "pages": args.pages, "chunks": (args.deck.stat().st_size + RANGE_CHUNK - 1) // RANGE_CHUNK,
            "join_window": args.join_window, "slides": args.slides, "slide_interval": args.slide_interval}
    print(f"machine: {meta['cpu']} × {meta['cores']}; loop {loop_name}; work dir {work_root}", flush=True)
    results = []
    for n in args.participants:
        print(f"\n=== N = {n} ===", flush=True)
        work = work_root / f"n{n}"
        work.mkdir(parents=True, exist_ok=True)
        res = asyncio.run(run_one(n, args, args.deck, work))
        results.append(res)
        if args.out_json:
            args.out_json.write_text(json.dumps({"meta": meta, "results": results}, indent=1, default=str))
        if args.out_md:
            args.out_md.write_text(markdown(results, meta))
    md = markdown(results, meta)
    print("\n" + md)
    print(f"logs: {work_root}")


if __name__ == "__main__":
    main()
