"""Roster fan-out under a conference-talk join storm.

* talk mode does not broadcast the participant names (workshop mode still does);
* the active-count broadcast is throttled, and the final count always goes out;
* host roster pushes are coalesced, and the final roster always goes out.
"""
import asyncio
import json
import threading
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from daemon import throttle as throttle_mod
from daemon import ws_publish
from daemon.participant import fanout
from daemon.participant import router as participant_router
from daemon.participant.state import participant_state


class _Railway:
    """Stand-in for the daemon's Railway WS client; records participant broadcasts."""

    def __init__(self):
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def send(self, msg):
        if msg.get("type") == "broadcast":
            with self._lock:
                self.events.append(msg["event"])
        return True

    def of_type(self, msg_type):
        with self._lock:
            return [e for e in self.events if e["type"] == msg_type]


@pytest.fixture
def railway(monkeypatch):
    rec = _Railway()
    monkeypatch.setattr(ws_publish, "_ws_client", rec)
    return rec


@pytest.fixture
def fresh_roster():
    participant_state.reset(mode="workshop")
    yield participant_state
    participant_state.reset(mode="workshop")


@pytest.fixture
def daemon_loop(monkeypatch):
    """A running loop in its own thread, registered as the daemon's event loop."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(throttle_mod, "get_event_loop", lambda: loop)
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ── Names broadcast: skipped in talk mode ──────────────────────────────────────


class TestNamesBroadcastByMode:
    def _join(self, ps, pid, name):
        ps.participant_names[pid] = name
        participant_router._publish_names_if_changed()

    def test_talk_mode_skips_names_broadcast_but_regenerates_attendees(
        self, railway, fresh_roster
    ):
        fresh_roster.mode = "talk"
        with patch.object(participant_router, "_regenerate_attendees") as regen:
            for i in range(5):
                self._join(fresh_roster, f"p{i}", f"Name {i}")
        assert railway.of_type("participant_names_updated") == []
        assert regen.call_count == 5  # attendees.md still follows every join

    def test_workshop_mode_still_broadcasts_names(self, railway, fresh_roster):
        with patch.object(participant_router, "_regenerate_attendees"):
            self._join(fresh_roster, "p1", "Alice")
            self._join(fresh_roster, "p2", "Bob")
        events = railway.of_type("participant_names_updated")
        assert len(events) == 2
        assert sorted(events[-1]["names"]) == ["Alice", "Bob"]


# ── Active-count broadcast: throttled, final value delivered ──────────────────


def test_active_count_ignores_unnamed_and_internal_ids(fresh_roster):
    fresh_roster.participant_names.update({"a": "A", "b": "B", "__host__": "Host"})
    fresh_roster.online_participants.update({"a", "b", "__host__", "not-registered"})
    assert fanout.active_participant_count() == 2


def test_presence_burst_coalesces_active_count_and_sends_the_final_value(
    railway, fresh_roster, daemon_loop, monkeypatch
):
    """500 people come online in a burst: the main thread asks for a broadcast
    after each one; participants get a handful, the last one carrying 500."""
    monkeypatch.setattr(fanout.active_count, "_interval", 0.2)
    for i in range(500):
        pid = f"p{i}"
        fresh_roster.participant_names[pid] = f"Name {i}"
        fresh_roster.online_participants.add(pid)  # what the presence handler does
        fanout.request_active_count_broadcast()  # from this (non-loop) thread

    def last_count():
        events = railway.of_type("active_participants_count_updated")
        return events[-1]["count"] if events else None

    assert _wait_until(lambda: last_count() == 500)
    time.sleep(0.5)  # nothing else is pending
    sent = railway.of_type("active_participants_count_updated")
    assert 1 <= len(sent) <= 3, [e["count"] for e in sent]
    assert sent[-1]["count"] == 500


def test_active_count_goes_out_on_a_later_change_too(
    railway, fresh_roster, daemon_loop, monkeypatch
):
    monkeypatch.setattr(fanout.active_count, "_interval", 0.1)
    fresh_roster.participant_names.update({"a": "A", "b": "B"})
    fresh_roster.online_participants.update({"a", "b"})
    fanout.request_active_count_broadcast()
    fresh_roster.online_participants.discard("b")
    fanout.request_active_count_broadcast()

    def counts():
        return [e["count"] for e in railway.of_type("active_participants_count_updated")]

    assert _wait_until(lambda: counts() and counts()[-1] == 1)
    assert counts()[-1] == 1


def test_active_count_without_daemon_loop_is_sent_directly(
    railway, fresh_roster, monkeypatch
):
    """At daemon startup Railway pushes the roster before the event loop is up:
    that count must not be dropped."""
    monkeypatch.setattr(throttle_mod, "get_event_loop", lambda: None)
    fresh_roster.participant_names["a"] = "A"
    fresh_roster.online_participants.add("a")
    fanout.request_active_count_broadcast()
    sent = railway.of_type("active_participants_count_updated")
    assert [e["count"] for e in sent] == [1]


# ── Host roster pushes: coalesced, final roster delivered ─────────────────────


class _HostWs:
    """Stand-in for the trainer's host-panel WS; records pushed frames."""

    def __init__(self):
        self.frames: list[dict] = []

    async def send_text(self, payload):
        self.frames.append(json.loads(payload))

    def rosters(self):
        return [f["participants"] for f in self.frames if f["type"] == "participant_list_updated"]


@pytest.fixture
def host_ws(monkeypatch):
    ws = _HostWs()
    monkeypatch.setattr(ws_publish, "_host_wss", {ws})
    return ws


def test_register_storm_coalesces_host_roster_pushes(
    railway, host_ws, fresh_roster, monkeypatch
):
    """200 people register back to back: the host gets the first join at once,
    then one trailing push carrying everybody, not 200 full rosters."""
    monkeypatch.setattr(fanout.host_roster, "_interval", 0.2)
    fresh_roster.mode = "talk"
    app = FastAPI()
    app.include_router(participant_router.router)

    async def storm():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://d") as c:
            for i in range(200):
                r = await c.post("/api/participant/register", json={},
                                 headers={"X-Participant-ID": f"p{i}"})
                assert r.status_code == 200
        assert len(host_ws.rosters()) == 1  # leading edge only so far
        await asyncio.sleep(0.5)

    with patch.object(participant_router, "_regenerate_attendees"):
        asyncio.run(storm())

    rosters = host_ws.rosters()
    assert len(rosters) == 2, [len(r) for r in rosters]
    assert len(rosters[0]) == 1
    assert {p["uuid"] for p in rosters[-1]} == {f"p{i}" for i in range(200)}


def test_presence_storm_from_main_thread_coalesces_host_roster(
    railway, host_ws, fresh_roster, daemon_loop, monkeypatch
):
    """Presence events run on the daemon main thread, not on the loop."""
    monkeypatch.setattr(fanout.host_roster, "_interval", 0.2)
    monkeypatch.setattr(fanout.active_count, "_interval", 0.2)
    for i in range(300):
        fresh_roster.participant_names[f"p{i}"] = f"Name {i}"
    for i in range(300):
        fanout.handle_participant_presence({"uuid": f"p{i}", "online": True})

    def all_online_in_last_roster():
        rosters = host_ws.rosters()
        return bool(rosters) and sum(p["online"] for p in rosters[-1]) == 300

    assert _wait_until(all_online_in_last_roster)
    time.sleep(0.5)
    assert 1 <= len(host_ws.rosters()) <= 3
    counts = railway.of_type("active_participants_count_updated")
    assert 1 <= len(counts) <= 3 and counts[-1]["count"] == 300


def test_presence_ignores_internal_ids_and_tracks_offline(
    railway, host_ws, fresh_roster, daemon_loop
):
    fresh_roster.participant_names.update({"a": "A", "b": "B"})
    fanout.handle_participant_presence({"uuid": "__host__", "online": True})
    fanout.handle_participant_presence({"uuid": "a", "online": True, "tz": "Europe/Bucharest"})
    fanout.handle_participant_presence({"uuid": "b", "online": True})
    fanout.handle_participant_presence({"uuid": "b", "online": False})
    assert fresh_roster.online_participants == {"a"}
    assert fresh_roster.location_timezones["a"] == "Europe/Bucharest"

    def last_count():
        sent = railway.of_type("active_participants_count_updated")
        return sent[-1]["count"] if sent else None

    assert _wait_until(lambda: last_count() == 1)
