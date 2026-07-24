"""End-to-end backend tests for the `participant-real-names` change (phase 1).

Covers the non-blocking duplicate contract, the UUID-free names broadcast + the
security invariant, and race conditions (concurrent same-name register,
concurrent rename, concurrent duplicate resolution). Driven against the real
participant router + real ParticipantState, with the WS publisher captured.
"""

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from httpx import ASGITransport
from starlette.testclient import TestClient

from daemon import ws_publish
from daemon.participant.router import router


class _Recorder:
    """Stand-in Railway WS client that records every broadcast the daemon sends."""

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)
        return True

    # ── query helpers ──
    def broadcasts(self, msg_type):
        return [
            m["event"]
            for m in self.sent
            if m.get("type") == "broadcast" and m.get("event", {}).get("type") == msg_type
        ]

    def last_names(self):
        events = self.broadcasts("participant_names_updated")
        return events[-1]["names"] if events else None


@contextmanager
def _env():
    """Fresh state + captured WS client. Yields (ParticipantState, _Recorder).

    Uses the REAL participant_state singleton (reset per test) because the host
    enumerator `_build_host_participants_list()` — which the names broadcast and
    the /state payload derive from — reads that singleton directly. Patching a
    separate instance would desync the two.
    """
    from daemon.participant.state import participant_state as real_ps
    from daemon.scores import scores as real_scores

    real_ps.reset(mode="workshop")
    real_scores.scores.clear()
    rec = _Recorder()
    try:
        with patch.object(ws_publish, "_ws_client", rec), \
             patch.object(ws_publish, "_host_wss", set()):
            yield real_ps, rec
    finally:
        real_ps.reset(mode="workshop")
        real_scores.scores.clear()


@contextmanager
def _client():
    with _env() as (ps, rec):
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app), ps, rec


def _register(client, uuid, name=None):
    body = {"name": name} if name is not None else {}
    return client.post(
        "/api/participant/register", json=body, headers={"X-Participant-ID": uuid}
    )


def _rename(client, uuid, name):
    return client.put(
        "/api/participant/name", json={"name": name}, headers={"X-Participant-ID": uuid}
    )


# ── Non-blocking duplicate contract (8.2 / 8.3 backend) ──────────────────────

class TestNonBlockingContract:
    def test_register_taken_name_never_409_and_flags(self):
        with _client() as (client, ps, rec):
            assert _register(client, "u1", "Alice").status_code == 200
            r2 = _register(client, "u2", "Alice")
            assert r2.status_code == 200
            body = r2.json()
            assert body["name"] == "Alice"
            assert body["name_conflict"] is True
            # Both admitted.
            assert ps.participant_names == {"u1": "Alice", "u2": "Alice"}

    def test_register_unique_name_no_conflict(self):
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            assert _register(client, "u2", "Bob").json()["name_conflict"] is False

    def test_rename_to_taken_name_never_409_and_flags(self):
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            _register(client, "u2", "Bob")
            r = _rename(client, "u2", "Alice")
            assert r.status_code == 200
            assert r.json()["name_conflict"] is True
            assert ps.participant_names["u2"] == "Alice"

    def test_name_cap_raised_to_64(self):
        with _client() as (client, ps, rec):
            long_name = "N" * 100
            r = _register(client, "u1", long_name)
            assert r.status_code == 200
            assert len(ps.participant_names["u1"]) == 64

    def test_anonymous_empty_body_assigns_fictional_name(self):
        with _client() as (client, ps, rec):
            r = _register(client, "u1", None)  # empty body => Anonymous path
            assert r.status_code == 200
            assert r.json()["name"]  # some auto-assigned name
            assert r.json()["name_conflict"] is False


# ── UUID-free names broadcast + SECURITY invariant (8.9) ─────────────────────

class TestNamesBroadcastSecurity:
    def test_names_broadcast_on_join(self):
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            _register(client, "u2", "Bob")
            assert sorted(rec.last_names()) == ["Alice", "Bob"]

    def test_names_broadcast_on_rename(self):
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            _register(client, "u2", "Bob")
            _rename(client, "u2", "Carol")
            assert sorted(rec.last_names()) == ["Alice", "Carol"]

    def test_duplicate_appears_twice_in_broadcast(self):
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            _register(client, "u2", "Alice")
            names = rec.last_names()
            assert names.count("Alice") == 2  # client detects duplicate by count>=2

    def test_no_uuid_in_any_participant_broadcast(self):
        """SECURITY: no participant-facing broadcast payload may contain a UUID."""
        uuids = ["11111111-aaaa-bbbb-cccc-000000000001",
                 "22222222-aaaa-bbbb-cccc-000000000002"]
        with _client() as (client, ps, rec):
            _register(client, uuids[0], "Alice")
            _register(client, uuids[1], "Bob")
            _rename(client, uuids[1], "Carol")
            # Inspect EVERY broadcast event the daemon emitted.
            events = [m["event"] for m in rec.sent
                      if m.get("type") == "broadcast"]
            assert events, "expected at least one participant broadcast"
            for ev in events:
                blob = repr(ev)
                for uid in uuids:
                    assert uid not in blob, f"UUID leaked in participant broadcast: {ev}"
                # names_updated must be names-only (no uuid-ish keys)
                if ev.get("type") == "participant_names_updated":
                    assert set(ev.keys()) <= {"type", "names"}

    def test_names_payload_model_has_only_names(self):
        from daemon.ws_messages import ParticipantNamesUpdatedMsg
        dumped = ParticipantNamesUpdatedMsg(names=["Alice", "Bob"]).model_dump()
        assert set(dumped.keys()) == {"type", "names"}
        assert "uuid" not in dumped and "participants" not in dumped

    def test_participant_state_endpoint_names_are_uuid_free(self):
        uuid = "33333333-aaaa-bbbb-cccc-000000000003"
        with _client() as (client, ps, rec):
            _register(client, uuid, "Alice")
            _register(client, "other-uuid-xyz", "Bob")
            state = client.get(
                "/api/participant/state", headers={"X-Participant-ID": uuid}
            ).json()
            assert sorted(state["participant_names"]) == ["Alice", "Bob"]
            assert uuid not in repr(state)
            assert "other-uuid-xyz" not in repr(state)


# ── Broadcast throttle: unchanged name-sets are not re-broadcast ─────────────

def _heartbeat(client, uuid):
    return client.post(
        "/api/participant/activity",
        json={"current_view": "slides", "deltas": {}},
        headers={"X-Participant-ID": uuid},
    )


class TestNamesBroadcastThrottle:
    def test_activity_heartbeat_does_not_rebroadcast_names(self):
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            before = len(rec.broadcasts("participant_names_updated"))
            assert _heartbeat(client, "u1").status_code == 204
            assert len(rec.broadcasts("participant_names_updated")) == before

    def test_rename_after_heartbeat_still_broadcasts(self):
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            _heartbeat(client, "u1")
            before = len(rec.broadcasts("participant_names_updated"))
            _rename(client, "u1", "Alicia")
            assert len(rec.broadcasts("participant_names_updated")) == before + 1
            assert rec.last_names() == ["Alicia"]

    def test_state_reset_forces_next_broadcast(self):
        """A new session re-broadcasts even if the first joiner reuses the exact
        name-set last broadcast in the previous session."""
        with _client() as (client, ps, rec):
            _register(client, "u1", "Alice")
            before = len(rec.broadcasts("participant_names_updated"))
            ps.reset(mode="workshop")
            _register(client, "u2", "Alice")
            assert len(rec.broadcasts("participant_names_updated")) == before + 1


# ── Race conditions / simultaneous changes (8.10) ────────────────────────────
# Driven with true async concurrency (asyncio.gather over the ASGI app).

def _run_concurrent(coro_factory):
    """Run an async scenario against the ASGI app; return (names_snapshot, rec, result).

    The names are snapshotted INSIDE the _env() context because _env resets the
    real singleton on exit.
    """
    async def _main():
        with _env() as (ps, rec):
            app = FastAPI()
            app.include_router(router)
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as ac:
                result = await coro_factory(ac, ps, rec)
            return dict(ps.participant_names), rec, result

    return asyncio.run(_main())


async def _areg(ac, uuid, name=None):
    body = {"name": name} if name is not None else {}
    return await ac.post(
        "/api/participant/register", json=body, headers={"X-Participant-ID": uuid}
    )


async def _aren(ac, uuid, name):
    return await ac.put(
        "/api/participant/name", json={"name": name}, headers={"X-Participant-ID": uuid}
    )


class TestRaceConditions:
    def test_concurrent_same_name_register_both_admitted_no_409(self):
        async def scenario(ac, ps, rec):
            return await asyncio.gather(
                _areg(ac, "u1", "Sam"), _areg(ac, "u2", "Sam")
            )

        names, rec, (r1, r2) = _run_concurrent(scenario)
        assert r1.status_code == 200 and r2.status_code == 200
        # Both admitted under the same name.
        assert names == {"u1": "Sam", "u2": "Sam"}
        # At least one observes the collision (order-dependent), neither is blocked.
        flags = {r1.json()["name_conflict"], r2.json()["name_conflict"]}
        assert True in flags
        # Final broadcast shows the name twice (duplicate detectable client-side).
        assert rec.last_names().count("Sam") == 2

    def test_concurrent_rename_converges(self):
        async def scenario(ac, ps, rec):
            await asyncio.gather(_areg(ac, "u1", "A"), _areg(ac, "u2", "B"))
            return await asyncio.gather(
                _aren(ac, "u1", "X"), _aren(ac, "u2", "Y")
            )

        names, rec, (r1, r2) = _run_concurrent(scenario)
        assert r1.status_code == 200 and r2.status_code == 200
        assert names == {"u1": "X", "u2": "Y"}
        assert sorted(rec.last_names()) == ["X", "Y"]

    def test_concurrent_duplicate_resolution_clears_for_both(self):
        """Both duplicates rename to unique names at once — no name is left duplicated."""
        async def scenario(ac, ps, rec):
            await asyncio.gather(_areg(ac, "u1", "Dup"), _areg(ac, "u2", "Dup"))
            assert rec.last_names().count("Dup") == 2  # duplicated before
            return await asyncio.gather(
                _aren(ac, "u1", "Unique1"), _aren(ac, "u2", "Unique2")
            )

        names, rec, _ = _run_concurrent(scenario)
        names = rec.last_names()
        # No duplicates remain — every name occurs exactly once.
        assert sorted(names) == ["Unique1", "Unique2"]
        assert len(names) == len(set(names))
