"""
Step definitions for qa.feature scenarios.
"""

import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from playwright.sync_api import expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from step_defs.conftest import _await_condition

# Link feature file
scenarios("../features/qa.feature")


# ── When steps ───────────────────────────────────────────────────────────────

@when(parsers.parse('the participant submits question "{text}"'))
def participant_submits_question(connected, text):
    connected["pax"].submit_question(text)


@when(parsers.parse('participant {n:d} submits question "{text}"'))
def participant_n_submits(connected_multi, n, text):
    connected_multi["pax_list"][n - 1].submit_question(text)


@when(parsers.parse('participant {n:d} upvotes the question containing "{fragment}"'))
def participant_n_upvotes(connected_multi, n, fragment):
    host = connected_multi["host"]
    _await_condition(
        lambda: any(fragment in q["text"] for q in host.get_qa_questions()),
        timeout_ms=5000,
        msg=f"Question containing '{fragment}' not found"
    )
    q = next(q for q in host.get_qa_questions() if fragment in q["text"])
    connected_multi["pax_list"][n - 1].upvote_question(q["id"])


@when("a new participant joins the session", target_fixture="new_pax")
def new_participant_joins(late_pax):
    return late_pax("LateJoiner")


# ── Then steps ───────────────────────────────────────────────────────────────

@then(parsers.parse('the host sees a question containing "{fragment}"'))
def host_sees_question(connected, fragment):
    host = connected["host"]
    _await_condition(
        lambda: any(fragment.lower() in q["text"].lower() for q in host.get_qa_questions()),
        timeout_ms=5000,
        msg=f"Host did not see question containing '{fragment}'"
    )


@then(parsers.parse("the question has {count:d} upvotes"))
def question_has_upvotes(connected, count):
    host = connected["host"]
    qs = host.get_qa_questions()
    assert len(qs) >= 1, "No questions found"
    assert qs[0]["upvotes"] == count, f"Expected {count} upvotes, got {qs[0]['upvotes']}"


@then(parsers.parse('question "{fragment}" has {count:d} upvotes'))
def named_question_has_upvotes(connected_multi, fragment, count):
    host = connected_multi["host"]
    _await_condition(
        lambda: any(
            fragment in q["text"] and q["upvotes"] == count
            for q in host.get_qa_questions()
        ),
        timeout_ms=5000,
        msg=f"Question '{fragment}' did not reach {count} upvotes"
    )
    q = next(q for q in host.get_qa_questions() if fragment in q["text"])
    assert q["upvotes"] == count, f"Expected {count} upvotes for '{fragment}', got {q['upvotes']}"


@then("questions are sorted by upvotes descending")
def questions_sorted_by_upvotes(connected_multi):
    host = connected_multi["host"]
    qs = host.get_qa_questions()
    upvotes = [q["upvotes"] for q in qs]
    assert upvotes == sorted(upvotes, reverse=True), f"Not sorted descending: {upvotes}"


@then(parsers.parse('the new participant sees question "{text}"'))
def new_pax_sees_question(new_pax, text):
    expect(new_pax._page.locator(f".qa-text-p:has-text('{text}')")).to_be_visible(timeout=5000)
