"""Step definitions for participant_login_name.feature.

These bind the human-readable Gherkin to the REAL daemon participant router,
the REAL ``participant_state`` singleton and the REAL ``attendees.md`` renderer —
the exact production code paths exercised by
``tests/daemon/test_participant_real_names.py``,
``tests/daemon/test_participant_sanitize.py`` and
``tests/daemon/test_attendees_md*.py`` — driven in-process via Starlette
TestClient. The Railway WebSocket publisher is captured by a recorder so we can
assert on the UUID-free names broadcast. No browser, no docker.
"""
import asyncio
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from pytest_bdd import given, parsers, scenarios, then, when
from starlette.testclient import TestClient

from daemon import attendees_md, ws_publish
from daemon.participant.router import router

scenarios("../participant_login_name.feature")


# ── Harness: real singleton + captured WS publisher ─────────────────────────


class _Recorder:
    """Stand-in Railway WS client that records every broadcast the daemon sends."""

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)
        return True

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
def _real_env():
    """Reset the real participant_state singleton + scores and capture WS sends.

    Mirrors ``tests/daemon/test_participant_real_names.py::_env`` — the host
    enumerator and attendees.md renderer both read the singleton directly, so a
    separate instance would desync them.
    """
    from unittest.mock import patch

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


@pytest.fixture
def bdd(tmp_path):
    """Per-scenario context: TestClient on the real router, recorder, and a real
    session folder for the on-disk attendees.md."""
    with _real_env() as (ps, rec):
        app = FastAPI()
        app.include_router(router)
        folder = tmp_path / "2026-07-24 AcmeCorp Workshop"
        folder.mkdir()
        yield {
            "client": TestClient(app),
            "app": app,
            "ps": ps,
            "rec": rec,
            "folder": folder,
            "names": {},  # uuid -> last assigned display name
        }


# ── Low-level helpers ───────────────────────────────────────────────────────


def _register(bdd, uuid, name=None):
    body = {"name": name} if name is not None else {}
    return bdd["client"].post(
        "/api/participant/register", json=body, headers={"X-Participant-ID": uuid}
    )


def _rename(bdd, uuid, name):
    return bdd["client"].put(
        "/api/participant/name", json={"name": name}, headers={"X-Participant-ID": uuid}
    )


def _rejoin(bdd, uuid):
    return bdd["client"].post(
        "/api/participant/rejoin", headers={"X-Participant-ID": uuid}
    )


def _attendees_text(bdd) -> str:
    """Regenerate the REAL attendees.md from the live roster and read it back."""
    target = attendees_md.regenerate_attendees(folder=bdd["folder"])
    return target.read_text()


def _all_broadcast_events(bdd):
    return [m["event"] for m in bdd["rec"].sent if m.get("type") == "broadcast"]


# ── Background ──────────────────────────────────────────────────────────────


@given("a fresh workshop session")
def _fresh_session(bdd):
    assert bdd["ps"].mode == "workshop"
    assert bdd["ps"].participant_names == {}


# ── Given: pre-joined participants ──────────────────────────────────────────


@given(parsers.parse('participant "{uuid}" has joined as "{name}"'))
def _given_joined(bdd, uuid, name):
    r = _register(bdd, uuid, name)
    assert r.status_code == 200
    bdd["names"][uuid] = r.json()["name"]


# ── When: gate / join / rename actions ──────────────────────────────────────


@when(parsers.parse('a brand-new participant "{uuid}" checks whether the session recognizes them'))
def _check_recognized(bdd, uuid):
    bdd["last_rejoin"] = _rejoin(bdd, uuid)


@when(parsers.parse('participant "{uuid}" enters the real name "{name}"'))
@when(parsers.parse('participant "{uuid}" joins as "{name}"'))
def _enter_real_name(bdd, uuid, name):
    r = _register(bdd, uuid, name)
    bdd["last_register"] = r
    if r.status_code == 200:
        bdd["names"][uuid] = r.json()["name"]


@when(parsers.parse('participant "{uuid}" types "{typed}" but logs in anonymously'))
def _login_anonymously(bdd, uuid, typed):
    # The frontend "Login anonymously" button sends an EMPTY body — the typed
    # text is deliberately discarded. Model that exactly.
    r = _register(bdd, uuid, None)
    assert r.status_code == 200
    bdd["names"][uuid] = r.json()["name"]
    bdd["typed"] = typed


@when(parsers.parse('participant "{uuid}" renames to "{name}"'))
def _rename_to(bdd, uuid, name):
    r = _rename(bdd, uuid, name)
    assert r.status_code == 200
    bdd["last_rename"] = r
    bdd["names"][uuid] = name


@when(parsers.parse('participant "{uuid}" returns to the same session'))
def _returns(bdd, uuid):
    bdd["last_rejoin"] = _rejoin(bdd, uuid)


@when("a new session starts")
def _new_session(bdd):
    # A brand-new session wipes the roster (same path daemon/__main__ uses).
    bdd["ps"].reset(mode="workshop")


@when(parsers.parse('participants "{u1}" and "{u2}" enter the name "{name}" at the same time'))
def _concurrent_same_name(bdd, u1, u2, name):
    app = bdd["app"]

    async def _scenario():
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            async def _areg(uid):
                return await ac.post(
                    "/api/participant/register",
                    json={"name": name},
                    headers={"X-Participant-ID": uid},
                )

            return await asyncio.gather(_areg(u1), _areg(u2))

    r1, r2 = asyncio.run(_scenario())
    bdd["concurrent"] = {"name": name, "r1": r1, "r2": r2}


@when(parsers.parse('participant "{uuid}" joins with the name "{shown}" spanning a newline'))
def _join_with_newline(bdd, uuid, shown):
    # The reviewer-facing text shows the folded form; the actual input carries a
    # real newline that an attacker hopes will split into a second table row.
    raw = "Ada\n99. Injected"
    r = _register(bdd, uuid, raw)
    assert r.status_code == 200
    bdd["names"][uuid] = r.json()["name"]


@when(parsers.parse('participant "{uuid}" joins with a name padded with control, ANSI and bidi characters'))
def _join_with_noise(bdd, uuid):
    # ANSI CSI colour codes + NUL control char + RLO bidi-override spoofing char.
    raw = "\x1b[31mRed\x1b[0m Name\x00‮"
    r = _register(bdd, uuid, raw)
    assert r.status_code == 200
    bdd["names"][uuid] = r.json()["name"]


@when(parsers.parse('participant "{uuid}" joins with the name "{name}"'))
def _join_with_literal_name(bdd, uuid, name):
    r = _register(bdd, uuid, name)
    assert r.status_code == 200
    bdd["names"][uuid] = r.json()["name"]


# ── Then: gate recognition ──────────────────────────────────────────────────


@then("the session does not recognize them")
def _not_recognized(bdd):
    assert bdd["last_rejoin"].status_code == 404


@then(parsers.parse('no name is committed for "{uuid}" yet'))
def _no_name_committed(bdd, uuid):
    assert uuid not in bdd["ps"].participant_names


@then(parsers.parse('the session recognizes them as "{name}"'))
def _recognized_as(bdd, name):
    r = bdd["last_rejoin"]
    assert r.status_code == 200
    assert r.json()["name"] == name


# ── Then: admission + attendance sheet ──────────────────────────────────────


@then(parsers.parse('participant "{uuid}" is admitted as "{name}"'))
def _admitted_as(bdd, uuid, name):
    r = bdd["last_register"]
    assert r.status_code == 200
    assert r.json()["name"] == name
    assert bdd["ps"].participant_names[uuid] == name


@then(parsers.parse('participant "{uuid}" is admitted without being blocked'))
def _admitted_not_blocked(bdd, uuid):
    r = bdd["last_register"]
    assert r.status_code == 200  # never a 409
    assert uuid in bdd["ps"].participant_names


@then(parsers.parse('participant "{uuid}" is flagged with a name conflict'))
def _flagged_conflict(bdd, uuid):
    assert bdd["last_register"].json()["name_conflict"] is True


@then(parsers.parse('participant "{uuid}" is admitted under an auto-assigned fictional name'))
def _admitted_fictional(bdd, uuid):
    assert bdd["ps"].participant_names[uuid]  # non-empty auto-assigned name
    assert uuid in bdd["ps"].anonymous_pids


@then(parsers.parse('participant "{uuid}" is not named "{typed}"'))
def _not_named(bdd, uuid, typed):
    assert bdd["ps"].participant_names[uuid] != typed


@then(parsers.parse('"{name}" appears on the attendance sheet'))
def _appears_on_sheet(bdd, name):
    assert name in _attendees_text(bdd)


@then(parsers.parse('"{name}" is not tagged anonymous on the attendance sheet'))
def _not_tagged_anon(bdd, name):
    text = _attendees_text(bdd)
    line = next(ln for ln in text.splitlines() if name in ln)
    assert "(anonymous)" not in line


@then(parsers.parse('participant "{uuid}" is tagged anonymous on the attendance sheet'))
def _tagged_anon(bdd, uuid):
    name = bdd["ps"].participant_names[uuid]
    text = _attendees_text(bdd)
    assert f"_{name}_ (anonymous)" in text


@then(parsers.parse("the attendance sheet reports {n:d} anonymous attendee"))
def _sheet_reports_anon(bdd, n):
    assert f"({n} anonymous)" in _attendees_text(bdd)


# ── Then: names broadcast ───────────────────────────────────────────────────


@then(parsers.parse('the participant-names broadcast lists "{name}" {n:d} times'))
def _broadcast_lists_n(bdd, name, n):
    names = bdd["rec"].last_names()
    assert names is not None, "no participant_names_updated broadcast captured"
    assert names.count(name) == n


@then("no name is duplicated in the participant-names broadcast")
def _no_dup_in_broadcast(bdd):
    names = bdd["rec"].last_names()
    assert names is not None
    assert len(names) == len(set(names)), f"duplicate remains: {names}"


@then("no participant broadcast contains any UUID")
def _no_uuid_in_any_broadcast(bdd):
    events = _all_broadcast_events(bdd)
    assert events, "expected at least one participant broadcast"
    uuids = [u for u in bdd["ps"].participant_names] + list(bdd["names"].keys())
    for ev in events:
        blob = repr(ev)
        for uid in uuids:
            assert uid not in blob, f"UUID leaked in participant broadcast: {ev}"


@then("every participant-names broadcast carries only the names field")
def _names_only_payload(bdd):
    for ev in bdd["rec"].broadcasts("participant_names_updated"):
        assert set(ev.keys()) <= {"type", "names"}


# ── Then: concurrency ───────────────────────────────────────────────────────


@then(parsers.parse('both participants are admitted under "{name}"'))
def _both_admitted(bdd, name):
    c = bdd["concurrent"]
    assert c["r1"].status_code == 200 and c["r2"].status_code == 200
    for uid in ("u1", "u2"):
        assert bdd["ps"].participant_names[uid] == name


@then("at least one participant detects the name conflict")
def _at_least_one_conflict(bdd):
    c = bdd["concurrent"]
    flags = {c["r1"].json()["name_conflict"], c["r2"].json()["name_conflict"]}
    assert True in flags


# ── Then: sanitization / injection ──────────────────────────────────────────


@then(parsers.parse('the stored name for "{uuid}" contains no newline'))
def _no_newline(bdd, uuid):
    stored = bdd["ps"].participant_names[uuid]
    assert "\n" not in stored and "\r" not in stored


@then("the attendance sheet has exactly one numbered attendee row")
def _one_numbered_row(bdd):
    text = _attendees_text(bdd)
    numbered = [ln for ln in text.splitlines() if ln[:1].isdigit()]
    assert len(numbered) == 1, f"expected 1 numbered row, got {numbered}"


@then(parsers.parse('the stored name for "{uuid}" is "{expected}"'))
def _stored_name_is(bdd, uuid, expected):
    assert bdd["ps"].participant_names[uuid] == expected


@then(parsers.parse('the stored name for "{uuid}" has no control, ANSI or bidi characters'))
def _stored_name_clean(bdd, uuid):
    stored = bdd["ps"].participant_names[uuid]
    assert all(ord(ch) >= 0x20 for ch in stored)  # no control chars
    assert "\x1b" not in stored and "[31m" not in stored  # no ANSI
    assert all(ord(ch) not in range(0x202A, 0x202F) for ch in stored)  # no bidi overrides


@then(parsers.parse('the stored name for "{uuid}" is kept as literal text'))
def _stored_literal(bdd, uuid):
    # Printable HTML is stored verbatim (inert data), not stripped — the sink
    # (attendees.md) is responsible for neutralizing it.
    assert bdd["ps"].participant_names[uuid] == "<img src=x onerror=alert(1)>"


@then("the attendance sheet escapes the name so no raw HTML tag survives")
def _sheet_escapes_html(bdd):
    text = _attendees_text(bdd)
    assert "\\<img src=x onerror=alert\\(1\\)\\>" in text
    # No UNescaped angle-bracket opener survives.
    assert text.replace("\\<", "").find("<") == -1
