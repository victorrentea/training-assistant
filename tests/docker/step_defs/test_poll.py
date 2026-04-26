"""
Step definitions for poll.feature scenarios.

Reuses shared conftest.py fixtures (`browser`, `session_id`) and the page
objects in `tests/pages/`. Named participants are tracked in this module's
`_participants` registry — the shared seq harness in conftest auto-detects it
to map UUIDs to display names for sequence-diagram extraction.
"""
import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")
sys.path.insert(0, "/tests")

import pytest  # noqa: I001
from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/poll.feature")


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

# Per-scenario state. `_participants` is auto-detected by the conftest seq
# harness — keeping the same name as test_slides.py is intentional (DRY).
_participants: dict[str, ParticipantPage] = {}
_ctx: dict = {}


@pytest.fixture(autouse=True)
def _reset_state():
    _participants.clear()
    _ctx.clear()
    yield
    _participants.clear()
    _ctx.clear()


# ── Helpers ────────────────────────────────────────────────────────────────

def _join_pax(browser, session_id, name: str) -> ParticipantPage:
    if name in _participants:
        return _participants[name]
    pctx = browser.new_context()
    page = pctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(page)
    pax.join(name)
    _participants[name] = pax
    return pax


def _host() -> HostPage:
    assert "host" in _ctx, "Host not connected — Background step must run first"
    return _ctx["host"]


def _option_id(option_text: str) -> str:
    """Map option text to its single-letter ID (A, B, C, ...) by index in poll."""
    options = _ctx.get("options", [])
    for i, t in enumerate(options):
        if t == option_text:
            return chr(65 + i)
    raise AssertionError(f"Option {option_text!r} not in poll options {options!r}")


def _the_pax() -> ParticipantPage:
    """The default singular 'the participant' is created by Background as 'Alice'."""
    assert "Alice" in _participants, "Default participant 'Alice' not joined"
    return _participants["Alice"]


def _vote(pax: ParticipantPage, *options: str) -> None:
    """Cast a vote via the participant API with awaited response.

    The participant's `castVote()` JS dispatches a fire-and-forget fetch, so the
    "Vote registered" toast appears before the daemon has acked. Tests that close
    the poll immediately after a vote then race the daemon and miss the vote.
    Using an awaited fetch here guarantees the daemon has processed the vote
    before the next step runs.
    """
    indices = [_ctx["options"].index(o) for o in options]
    import json as _json
    pax._page.evaluate(f"""async () => {{
        const r = await fetch('/' + _sessionId + '/api/participant/poll/vote', {{
            method: 'POST',
            headers: {{'Content-Type':'application/json','X-Participant-ID':_myUUID}},
            body: JSON.stringify({{options: {_json.dumps(indices)}}})
        }});
        // 409 means "already voted" — surface it so the test fails meaningfully
        // instead of silently accepting the previous vote.
        if (!r.ok) throw new Error('Vote failed: ' + r.status);
    }}""")


def _setup_poll(browser, session_id, question: str, options_str: str, multi: bool) -> None:
    hctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
    hpage = hctx.new_page()
    hpage.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
    expect(hpage.locator("#tab-poll")).to_be_visible(timeout=10000)
    host = HostPage(hpage)
    options = [o.strip() for o in options_str.split(";")]
    host.create_poll(question, options, multi=multi)
    _ctx["host"] = host
    _ctx["options"] = options
    _ctx["multi"] = multi
    # Default participant for "the participant" steps
    _join_pax(browser, session_id, "Alice")


# ── Background ─────────────────────────────────────────────────────────────

@given(parsers.parse('a poll "{question}" with options "{options}"'))
def given_poll(browser, session_id, question, options):
    _setup_poll(browser, session_id, question, options, multi=False)


@given(parsers.parse('a multi-select poll "{question}" with options "{options}"'))
def given_multi_select_poll(browser, session_id, question, options):
    _setup_poll(browser, session_id, question, options, multi=True)


@given("the poll is already open")
def given_poll_already_open():
    expect(_host()._page.locator("#poll-display.voting-active")).to_be_visible(timeout=5000)


# ── Vote actions ──────────────────────────────────────────────────────────

@given(parsers.parse('the participant selects "{option}"'))
@when(parsers.parse('the participant selects "{option}"'))
def the_participant_selects(option):
    _vote(_the_pax(), option)


_NAMED_PAX_RE_SELECT_TWO = (
    r'^a participant "(?P<name>[A-Z][a-zA-Z]+)" selects '
    r'"(?P<a>[^"]+)" and "(?P<b>[^"]+)"$'
)
_NAMED_PAX_RE_SELECT_ONLY = (
    r'^a participant "(?P<name>[A-Z][a-zA-Z]+)" selects "(?P<option>[^"]+)" only$'
)
_NAMED_PAX_RE_SELECT_AFTER = (
    r'^a participant "(?P<name>[A-Z][a-zA-Z]+)" selects "(?P<option>[^"]+)" '
    r'after (?P<seconds>\d+) seconds?$'
)
_NAMED_PAX_RE_SELECT = (
    r'^a participant "(?P<name>[A-Z][a-zA-Z]+)" selects "(?P<option>[^"]+)"$'
)


# Order matters: pytest-bdd picks the first registered step that matches.
# The two-option / "only" / "after Ns" variants must be registered BEFORE the
# generic single-option pattern, otherwise the generic one captures the longer
# strings (e.g. option=`Java" and "Kotlin`).

@given(parsers.re(_NAMED_PAX_RE_SELECT_TWO))
def named_pax_selects_two(browser, session_id, name, a, b):
    pax = _join_pax(browser, session_id, name)
    _vote(pax, a, b)


@given(parsers.re(_NAMED_PAX_RE_SELECT_ONLY))
def named_pax_selects_only(browser, session_id, name, option):
    pax = _join_pax(browser, session_id, name)
    _vote(pax, option)


@given(parsers.re(_NAMED_PAX_RE_SELECT_AFTER))
def named_pax_selects_after(browser, session_id, name, option, seconds):
    pax = _join_pax(browser, session_id, name)
    time.sleep(int(seconds))
    _vote(pax, option)


@given(parsers.re(_NAMED_PAX_RE_SELECT))
@when(parsers.re(_NAMED_PAX_RE_SELECT))
def named_pax_selects(browser, session_id, name, option):
    pax = _join_pax(browser, session_id, name)
    _vote(pax, option)


# ── Late joiner ────────────────────────────────────────────────────────────

@when(parsers.parse('a new participant "{name}" joins the session'))
def new_participant_joins(browser, session_id, name):
    _join_pax(browser, session_id, name)


# ── Host actions ───────────────────────────────────────────────────────────

@given("the host closes the poll")
@when("the host closes the poll")
def host_closes_poll():
    _host().close_poll()


def _reveal(option_texts: list[str]) -> None:
    ids = [_option_id(t) for t in option_texts]
    _host().reveal_correct(ids)


@given(parsers.parse('the host marks "{option}" as correct option'))
@when(parsers.parse('the host marks "{option}" as correct option'))
def host_marks_correct(option):
    _reveal([option])


@when(parsers.parse('the host marks "{a}" and "{b}" as correct options'))
def host_marks_two_correct(a, b):
    _reveal([a, b])


# ── Participant page reload ────────────────────────────────────────────────

@when("the participant refreshes the page")
def participant_refreshes():
    pax = _the_pax()
    pax._page.reload(wait_until="networkidle")
    # Wait for re-init: display-name appears after rejoin
    expect(pax._page.locator("#display-name .display-name-text")).to_have_text(
        "Alice", timeout=10000
    )


# ── Assertions on participant ──────────────────────────────────────────────

@then("the participant sees the question and options")
def pax_sees_poll():
    pax = _the_pax()
    expect(pax._page.locator(".poll-card h2")).to_be_visible(timeout=5000)
    expect(pax._page.locator(".option-btn")).to_have_count(
        len(_ctx["options"]), timeout=5000
    )


def _wait_for_pax_vote_in_daemon(pax: ParticipantPage, timeout_s: float = 5) -> None:
    """Poll the daemon's host poll state until the participant's vote is registered."""
    import json as _json
    uuid = pax._page.evaluate("() => localStorage.getItem('workshop_participant_uuid')")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            has_vote = _host()._page.evaluate(f"""async () => {{
                const r = await fetch(API('/poll'));
                if (!r.ok) return false;
                const data = await r.json();
                return !!(data.votes && data.votes[{_json.dumps(uuid)}]);
            }}""")
            if has_vote:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise AssertionError(f"Daemon did not register vote for pax {uuid[:8]} within {timeout_s}s")


@then("the vote is recorded")
def vote_is_recorded():
    _wait_for_pax_vote_in_daemon(_the_pax())


@then(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+)'s vote is recorded$"))
def named_vote_recorded(name):
    _wait_for_pax_vote_in_daemon(_participants[name])


@then("the participant cannot vote anymore")
def cannot_vote():
    pax = _the_pax()
    # All option buttons disabled after close
    buttons = pax._page.locator(".option-btn")
    count = buttons.count()
    assert count > 0, "No option buttons rendered"
    for i in range(count):
        expect(buttons.nth(i)).to_be_disabled(timeout=5000)


@then(parsers.parse('the participant sees "{option}" as the correct response'))
def pax_sees_correct(option):
    btn = _the_pax()._page.locator(f".option-btn:has-text('{option}')")
    expect(btn.locator(".result-icon")).to_be_visible(timeout=5000)


def _wait_for_score(pax: ParticipantPage, expected: int, timeout_ms: int = 8000) -> None:
    if expected == 0:
        # Score element is hidden at 0; let any update settle then assert.
        time.sleep(1.0)
        actual = pax.get_score()
        assert actual == 0, f"Expected 0 points, got {actual}"
        return
    deadline = time.monotonic() + timeout_ms / 1000
    last = -1
    while time.monotonic() < deadline:
        last = pax.get_score()
        if last == expected:
            return
        time.sleep(0.2)
    # Surface daemon-side scores + votes to make debugging the test failure easy.
    try:
        host_state = _host()._page.evaluate("""async () => {
            const pollR = await fetch(API('/poll'));
            const stateR = await fetch(API('/state'));
            return {
                poll: pollR.ok ? await pollR.json() : null,
                state: stateR.ok ? await stateR.json() : null,
            };
        }""")
        poll = host_state.get("poll") or {}
        state = host_state.get("state") or {}
        votes = poll.get("votes", {})
        scores_per_pax = {p["uuid"][:8]: p.get("score", 0) for p in state.get("participants", [])}
        uuid = pax._page.evaluate(
            "() => localStorage.getItem('workshop_participant_uuid')"
        )
        debug = (
            f"\n  pax_uuid={uuid[:8] if uuid else None}\n"
            f"  daemon_votes={ {k[:8]: v for k, v in votes.items()} }\n"
            f"  daemon_correct_indices={poll.get('correct_indices')}\n"
            f"  daemon_scores_by_uuid={scores_per_pax}"
        )
    except Exception as e:
        debug = f"\n  (could not fetch daemon state: {e})"
    raise AssertionError(
        f"Expected {expected} points within {timeout_ms}ms, got {last}{debug}"
    )


@then(parsers.parse("the participant is awarded {n:d} points"))
@given(parsers.parse("the participant is awarded {n:d} points"))
def participant_awarded(n):
    _wait_for_score(_the_pax(), n)


@then(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+) is awarded (?P<n>\d+) points$"))
@given(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+) is awarded (?P<n>\d+) points$"))
def named_awarded(name, n):
    _wait_for_score(_participants[name], int(n))


@then(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+) is awarded fewer than (?P<n>\d+) points$"))
def named_awarded_fewer_than(name, n):
    pax = _participants[name]
    time.sleep(1.5)
    actual = pax.get_score()
    n_int = int(n)
    assert 0 < actual < n_int, f"Expected 0 < score < {n_int} for {name}, got {actual}"


@then(parsers.re(
    r"^(?P<name>[A-Z][a-zA-Z]+) is awarded fewer points than (?P<other>[A-Z][a-zA-Z]+)$"
))
def named_awarded_fewer_than_other(name, other):
    time.sleep(1.5)
    a = _participants[name].get_score()
    b = _participants[other].get_score()
    assert a < b, f"Expected {name}'s score ({a}) < {other}'s score ({b})"


@then(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+)'s points are greater than (?P<n>\d+)$"))
def named_points_gt(name, n):
    time.sleep(1.5)
    actual = _participants[name].get_score()
    n_int = int(n)
    assert actual > n_int, f"Expected {name}'s points > {n_int}, got {actual}"


@then(parsers.parse("the participant's score is still {n:d}"))
def pax_score_still(n):
    _wait_for_score(_the_pax(), n)


# ── Assertions on host UI ─────────────────────────────────────────────────

@then(parsers.parse("the participant's score in host UI is {n:d}"))
def pax_score_in_host(n):
    _wait_for_host_score("Alice", n)


@then(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+)'s score in host UI is (?P<n>\d+)$"))
def named_score_in_host(name, n):
    _wait_for_host_score(name, int(n))


@then(parsers.re(
    r"^(?P<name>[A-Z][a-zA-Z]+)'s score in host UI is greater than (?P<other>[A-Z][a-zA-Z]+)'s score$"
))
def host_compares_scores(name, other):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        scores = _host().get_participant_scores()
        a = scores.get(name, -1)
        b = scores.get(other, -1)
        if a > b > 0:
            return
        time.sleep(0.3)
    raise AssertionError(f"Expected host {name}>{other} (got {a} vs {b})")


def _wait_for_host_score(name: str, expected: int, timeout_ms: int = 8000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    last = None
    while time.monotonic() < deadline:
        scores = _host().get_participant_scores()
        last = scores.get(name)
        if last == expected:
            return
        time.sleep(0.3)
    raise AssertionError(f"Host UI: expected {name}={expected}, got {last}")


@given(parsers.parse('the host sees {n:d} vote for "{option}"'))
@given(parsers.parse('the host sees {n:d} votes for "{option}"'))
@then(parsers.parse('the host sees {n:d} vote for "{option}"'))
@then(parsers.parse('the host sees {n:d} votes for "{option}"'))
def host_sees_votes(n, option):
    deadline = time.monotonic() + 5
    last = None
    while time.monotonic() < deadline:
        last = _host().get_vote_count_for(option)
        if last == n:
            return
        time.sleep(0.2)
    raise AssertionError(f"Host UI: expected {n} vote(s) for {option!r}, got {last}")


@given(parsers.parse("the host sees {n:d} vote received"))
@given(parsers.parse("the host sees {n:d} votes received"))
@then(parsers.parse("the host sees {n:d} vote received"))
@then(parsers.parse("the host sees {n:d} votes received"))
def host_sees_voted(n):
    deadline = time.monotonic() + 5
    last = None
    while time.monotonic() < deadline:
        last = _host().get_voted_count()
        if last == n:
            return
        time.sleep(0.2)
    raise AssertionError(f"Host UI: expected {n} voter(s), got {last}")
