"""Micro-benchmark: daemon fan-out during a conference-talk join storm.

Not a test (no ``test_`` prefix, never collected). Simulates N participants who
each POST /api/participant/register and then come online over the Railway WS
(``participant_presence``), all within a few seconds, in a talk session. Counts
what the daemon sends:

* participant broadcasts through Railway (each one fans out to EVERY participant),
* pushes to the host browser (each ``participant_list_updated`` is a full roster
  that host.js re-renders),

and times the per-join attendees.md regeneration plus ``participant_state.persist()``
(what the talk-mode emoji counter broadcast does every 0.5 s) at full roster size.

Run from the repo root:
    uv run --extra dev --extra daemon python tests/load/daemon_join_storm_bench.py [N] [SECONDS]
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

N = int(sys.argv[1]) if len(sys.argv) > 1 else 500
SPREAD_S = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0


class _Railway:
    """Stand-in for the daemon's Railway WS client — counts broadcasts and bytes."""

    def __init__(self):
        self.count = Counter()
        self.bytes = Counter()
        self.fanout_msgs = Counter()   # what Railway delivers: one copy per online participant
        self.fanout_bytes = Counter()
        self.last = {}
        self._lock = threading.Lock()

    def send(self, msg):
        if msg.get("type") == "broadcast":
            from daemon.participant.state import participant_state

            ev = msg["event"]
            size = len(json.dumps(ev))
            online = len(tuple(participant_state.online_participants))
            with self._lock:
                self.count[ev["type"]] += 1
                self.bytes[ev["type"]] += size
                self.fanout_msgs[ev["type"]] += online
                self.fanout_bytes[ev["type"]] += online * size
                self.last[ev["type"]] = ev
        return True


class _HostWs:
    """Stand-in for the trainer's host-panel WS — counts pushes and bytes."""

    def __init__(self):
        self.count = Counter()
        self.bytes = Counter()
        self.last = {}

    async def send_text(self, payload):
        ev = json.loads(payload)
        self.count[ev["type"]] += 1
        self.bytes[ev["type"]] += len(payload)
        self.last[ev["type"]] = ev


def _presence_handler():
    """The real main-thread presence handler (daemon.participant.fanout)."""
    from daemon.participant.fanout import handle_participant_presence

    return handle_participant_presence


def main() -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from daemon import loop as daemon_loop
    from daemon import ws_publish
    from daemon.participant.router import router as participant_router
    from daemon.participant.state import participant_state
    from daemon.session import state as session_shared_state

    tmp = Path(tempfile.mkdtemp(prefix="join-storm-"))
    (tmp / "2026-10-06 Talk").mkdir()
    session_shared_state.set_sessions_root(tmp)
    session_shared_state.set_active_session("talk01", "2026-10-06 Talk")
    participant_state.reset(mode="talk")

    railway, host = _Railway(), _HostWs()
    ws_publish.set_ws_client(railway)
    ws_publish.set_host_ws(host)

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    daemon_loop._loop = loop  # what host_server's lifespan does at startup

    app = FastAPI()
    app.include_router(participant_router)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://daemon")
    presence = _presence_handler()

    pids = [str(uuid.uuid4()) for _ in range(N)]
    t0 = time.perf_counter()
    for i, pid in enumerate(pids):
        # talk.html awaits /register, then opens its WS — so Railway's presence
        # event reaches the daemon main thread (ws_client.drain_queue) after it.
        resp = asyncio.run_coroutine_threadsafe(
            client.post("/api/participant/register", json={},
                        headers={"X-Participant-ID": pid}),
            loop,
        ).result(timeout=30)
        assert resp.status_code == 200
        presence({"uuid": pid, "online": True, "tz": "Europe/Bucharest"})
        delay = t0 + SPREAD_S * (i + 1) / N - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    storm_s = time.perf_counter() - t0
    time.sleep(2.5)  # let trailing-edge pushes land

    print(f"\n{N} registers + {N} presence events in {storm_s:.1f}s (talk mode)")
    print("\nParticipant broadcasts via Railway (each fans out to every participant):")
    for t, c in sorted(railway.count.items()):
        print(f"  {t:40s} {c:6d} msgs  {railway.bytes[t] / 1024:9.1f} KiB sent by daemon"
              f"  -> {railway.fanout_msgs[t]:7d} deliveries,"
              f" {railway.fanout_bytes[t] / 2**20:7.1f} MiB from Railway")
    print("\nHost browser pushes:")
    for t, c in sorted(host.count.items()):
        print(f"  {t:40s} {c:6d} msgs  {host.bytes[t] / 1024:9.1f} KiB")

    final_count = railway.last.get("active_participants_count_updated", {}).get("count")
    final_roster = len(host.last.get("participant_list_updated", {}).get("participants", []))
    print(f"\nFinal active count broadcast: {final_count}   final host roster size: {final_roster}")

    # Cost of the per-join attendees.md regeneration and of persist() at full size.
    from daemon.participant.router import _regenerate_attendees

    reps = 20
    t = time.perf_counter()
    for _ in range(reps):
        _regenerate_attendees()
    print(f"attendees.md regeneration @ {N}: {(time.perf_counter() - t) / reps * 1000:.1f} ms each")
    participant_state.emoji_counters["❤️"] = 1
    t = time.perf_counter()
    for i in range(reps):
        participant_state.emoji_counters["❤️"] = i + 2  # force a real write each time
        participant_state.persist()
    print(f"participant_state.persist() @ {N}: {(time.perf_counter() - t) / reps * 1000:.1f} ms each")
    size = (tmp / "2026-10-06 Talk" / "session-state.json").stat().st_size
    print(f"session-state.json size: {size / 1024:.1f} KiB")

    loop.call_soon_threadsafe(loop.stop)


if __name__ == "__main__":
    main()
