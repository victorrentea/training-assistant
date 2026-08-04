"""Trainer identity: claimed over loopback, never grantable through Railway."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.participant.sanitize import RESERVED_TRAINER_NAME
from daemon.participant.state import participant_state


@pytest.fixture(autouse=True)
def clean_state():
    participant_state.reset()
    yield
    participant_state.reset()


def test_trainer_pids_round_trip_and_reset():
    participant_state.trainer_pids.add("uuid-a")
    assert participant_state.snapshot()["trainer_pids"] == ["uuid-a"]

    participant_state.reset()
    assert participant_state.trainer_pids == set()

    participant_state.sync_from_restore({"trainer_pids": ["uuid-b"]})
    assert participant_state.trainer_pids == {"uuid-b"}


def _claim_client() -> TestClient:
    from daemon.host_machine.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _participant_client() -> TestClient:
    from daemon.participant.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_claim_then_register_yields_the_trainer_name():
    _claim_client().post("/api/host-machine/claim-trainer", json={"participant_id": "t1"})
    r = _participant_client().post(
        "/api/participant/register", json={}, headers={"X-Participant-ID": "t1"}
    )
    assert r.status_code == 200
    assert r.json()["name"] == RESERVED_TRAINER_NAME


def test_register_then_claim_also_yields_the_trainer_name():
    _participant_client().post(
        "/api/participant/register",
        json={"name": "Ordinary"},
        headers={"X-Participant-ID": "t2"},
    )
    r = _claim_client().post("/api/host-machine/claim-trainer", json={"participant_id": "t2"})
    assert r.json() == {"granted": True, "display_name": RESERVED_TRAINER_NAME}
    assert participant_state.participant_names["t2"] == RESERVED_TRAINER_NAME


def test_leaderboard_marks_the_claimed_trainer():
    """The badge comes from trainer_pids, not from the display string."""
    from daemon.leaderboard.router import router as leaderboard_router
    from daemon.scores import scores

    participant_state.trainer_pids.add("t1")
    participant_state.participant_names["t1"] = RESERVED_TRAINER_NAME
    participant_state.participant_names["p2"] = "Ordinary"
    scores.reset()
    scores.add_score("t1", 5)
    scores.add_score("p2", 3)

    app = FastAPI()
    app.include_router(leaderboard_router)
    entries = TestClient(app).post("/api/s1/host/leaderboard/show").json()["entries"]

    by_name = {e["name"]: e["is_trainer"] for e in entries}
    assert by_name == {RESERVED_TRAINER_NAME: True, "Ordinary": False}
    scores.reset()
