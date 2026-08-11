"""The trainer display name may only be held by a UUID that claimed it locally.

Without this gate the whole feature is an impersonation vector: the auto-switch
sets the reserved name, and any participant could otherwise simply type it.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.participant.router import router
from daemon.participant.sanitize import RESERVED_TRAINER_NAME, is_reserved_trainer_name
from daemon.participant.state import participant_state

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    participant_state.reset()
    yield
    participant_state.reset()


@pytest.mark.parametrize(
    "variant",
    [
        RESERVED_TRAINER_NAME,
        "  🧑‍🏫   victor   RENTEA ",
        "🧑‍🏫VICTOR Rentea",
        "🧑‍🏫Victor Rentea",  # NBSP instead of a plain space
    ],
)
def test_reserved_name_matches_case_and_spacing_variants(variant):
    assert is_reserved_trainer_name(variant)


@pytest.mark.parametrize(
    "other",
    # "Victor Rentea" without the badge is deliberately NOT reserved: only the
    # emoji-prefixed form is the trainer identity.
    ["Victor", "Victor Rentea", "Viktor Rentea", "🧑‍🏫Alice", "", None],
)
def test_ordinary_names_are_not_reserved(other):
    assert not is_reserved_trainer_name(other)


def test_impostor_cannot_register_under_the_reserved_name():
    r = client.post(
        "/api/participant/register",
        json={"name": RESERVED_TRAINER_NAME},
        headers={"X-Participant-ID": "impostor"},
    )
    assert r.status_code == 403
    assert participant_state.participant_names.get("impostor") != RESERVED_TRAINER_NAME


def test_impostor_cannot_register_under_a_normalized_variant():
    r = client.post(
        "/api/participant/register",
        json={"name": "  🧑‍🏫   victor   RENTEA "},
        headers={"X-Participant-ID": "impostor2"},
    )
    assert r.status_code == 403


def test_impostor_cannot_rename_into_the_reserved_name():
    client.post(
        "/api/participant/register",
        json={"name": "Ordinary"},
        headers={"X-Participant-ID": "impostor3"},
    )
    r = client.put(
        "/api/participant/name",
        json={"name": RESERVED_TRAINER_NAME},
        headers={"X-Participant-ID": "impostor3"},
    )
    assert r.status_code == 403
    assert participant_state.participant_names["impostor3"] == "Ordinary"


def test_claimed_trainer_may_hold_the_reserved_name():
    participant_state.trainer_pids.add("trainer")
    r = client.post(
        "/api/participant/register",
        json={"name": RESERVED_TRAINER_NAME},
        headers={"X-Participant-ID": "trainer"},
    )
    assert r.status_code == 200
    assert participant_state.participant_names["trainer"] == RESERVED_TRAINER_NAME
