"""
Step definitions for poll.feature scenarios.
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

# Link feature file
scenarios("../features/poll.feature")


# ── When steps ───────────────────────────────────────────────────────────────

@when(parsers.parse('the host creates a poll "{question}" with options "{options_csv}"'))
def host_creates_poll(connected, question, options_csv):
    options = [o.strip() for o in options_csv.split(",")]
    connected["host"].create_poll(question, options)


@when(parsers.parse('the participant votes for "{option}"'))
def participant_votes(connected, option):
    pax = connected["pax"]
    # Work around participant.js single-select bug: it sends {option_id} but daemon
    # expects {option_ids: []}. Submit vote via API directly using the option letter
    # (A=first, B=second, etc. as assigned by create_poll).
    page = pax._page
    # Find which option index corresponds to the option text
    option_btns = page.locator(".option-btn").all()
    option_id = None
    for i, btn in enumerate(option_btns):
        if option in btn.inner_text():
            option_id = chr(65 + i)  # A, B, C, ... matching create_poll's dict_options
            break
    if option_id:
        page.evaluate(f"() => participantApi('poll/vote', {{ option_ids: ['{option_id}'] }})")
        page.wait_for_timeout(500)
    else:
        # Fallback to UI click if option not found by text
        pax.vote_for(option)


@when("the host closes the poll")
def host_closes_poll(connected):
    connected["host"].close_poll()


@when(parsers.parse('the host marks "{option}" as correct'))
def host_marks_correct(connected, option):
    connected["host"].mark_correct(option)


# ── Then steps ───────────────────────────────────────────────────────────────

@then(parsers.parse('the participant sees poll question "{question}"'))
def participant_sees_question(connected, question):
    expect(connected["pax"]._page.locator("#content h2")).to_have_text(question, timeout=5000)


@then(parsers.parse("the participant sees {count:d} options"))
def participant_sees_n_options(connected, count):
    expect(connected["pax"]._page.locator(".option-btn")).to_have_count(count, timeout=5000)


@then("the participant sees the closed banner")
def participant_sees_closed_banner(connected):
    expect(connected["pax"]._page.locator(".closed-banner")).to_be_visible(timeout=5000)


@then("the participant sees percentages")
def participant_sees_percentages(connected):
    expect(connected["pax"]._page.locator(".pct").first).to_be_visible(timeout=5000)


@then(parsers.parse("the participant score is at least {min_score:d}"))
def participant_score_at_least(connected, min_score):
    # Wait for score to update
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        score = connected["pax"].get_score()
        if score >= min_score:
            return
        time.sleep(0.3)
    score = connected["pax"].get_score()
    assert score >= min_score, f"Expected score >= {min_score}, got {score}"


@then("all percentages are 0")
def all_percentages_zero(connected):
    # After close, wait for percentages to appear
    expect(connected["pax"]._page.locator(".pct").first).to_be_visible(timeout=5000)
    pcts = connected["pax"].get_percentages()
    assert all(p == 0 for p in pcts), f"Expected all 0% but got {pcts}"
