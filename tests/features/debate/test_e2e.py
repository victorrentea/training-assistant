"""E2E tests for routers/debate.py — full debate lifecycle via HTTP API."""
import pytest
from conftest import api, sapi


@pytest.fixture(autouse=True)
def clean_debate(server_url):
    sapi(server_url, "post", "/debate/reset")
    yield
    sapi(server_url, "post", "/debate/reset")


class TestDebateLaunchReset:
    def test_launch(self, server_url):
        resp = sapi(server_url, "post", "/debate", json={"statement": "AI is the future"})
        assert resp.status_code == 200
        assert resp.json()["ok"]

    def test_launch_empty_statement(self, server_url):
        resp = sapi(server_url, "post", "/debate", json={"statement": ""})
        assert resp.status_code == 400

    def test_reset(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/reset")
        assert resp.status_code == 200


class TestPhaseAdvance:
    def test_advance_to_arguments(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/phase", json={"phase": "arguments"})
        assert resp.status_code == 200
        assert resp.json()["phase"] == "arguments"

    def test_invalid_phase(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/phase", json={"phase": "invalid"})
        assert resp.status_code == 400

    def test_advance_without_debate(self, server_url):
        resp = sapi(server_url, "post", "/debate/phase", json={"phase": "arguments"})
        assert resp.status_code == 400

    def test_advance_to_live_debate(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        assert resp.status_code == 200

    def test_advance_to_ended(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/phase", json={"phase": "ended"})
        assert resp.status_code == 200


class TestCloseSelection:
    def test_close_selection_not_in_phase(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "arguments"})
        resp = sapi(server_url, "post", "/debate/close-selection")
        assert resp.status_code == 400

    def test_close_selection_ok(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/close-selection")
        assert resp.status_code == 200


class TestForceAssign:
    def test_force_assign_not_in_phase(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "arguments"})
        resp = sapi(server_url, "post", "/debate/force-assign")
        assert resp.status_code == 400

    def test_force_assign_no_participants(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/force-assign")
        assert resp.status_code == 400


class TestFirstSide:
    def test_set_first_side(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        resp = sapi(server_url, "post", "/debate/first-side", json={"side": "for"})
        assert resp.status_code == 200

    def test_invalid_side(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        resp = sapi(server_url, "post", "/debate/first-side", json={"side": "neither"})
        assert resp.status_code == 400

    def test_not_in_live_debate(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/first-side", json={"side": "for"})
        assert resp.status_code == 400


class TestSubPhaseTimer:
    def test_start_timer(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        sapi(server_url, "post", "/debate/first-side", json={"side": "for"})
        resp = sapi(server_url, "post", "/debate/round-timer",
                   json={"round_index": 0, "seconds": 120})
        assert resp.status_code == 200

    def test_invalid_index(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        sapi(server_url, "post", "/debate/first-side", json={"side": "for"})
        resp = sapi(server_url, "post", "/debate/round-timer",
                   json={"round_index": 99, "seconds": 120})
        assert resp.status_code == 400

    def test_zero_seconds(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        sapi(server_url, "post", "/debate/first-side", json={"side": "for"})
        resp = sapi(server_url, "post", "/debate/round-timer",
                   json={"round_index": 0, "seconds": 0})
        assert resp.status_code == 400

    def test_no_first_side(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        resp = sapi(server_url, "post", "/debate/round-timer",
                   json={"round_index": 0, "seconds": 60})
        assert resp.status_code == 400


class TestEndSubPhase:
    def test_end_active_timer(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        sapi(server_url, "post", "/debate/first-side", json={"side": "for"})
        sapi(server_url, "post", "/debate/round-timer",
            json={"round_index": 0, "seconds": 120})
        resp = sapi(server_url, "post", "/debate/end-round")
        assert resp.status_code == 200

    def test_no_active_timer(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "live_debate"})
        resp = sapi(server_url, "post", "/debate/end-round")
        assert resp.status_code == 400


class TestEndArguments:
    def test_not_in_arguments(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/end-arguments")
        assert resp.status_code == 400

    def test_no_arguments_skips_ai(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "arguments"})
        resp = sapi(server_url, "post", "/debate/end-arguments")
        assert resp.status_code == 200


class TestAiRequestAndResult:
    def test_poll_ai_request_empty(self, server_url):
        resp = sapi(server_url, "get", "/debate/ai-request")
        assert resp.status_code == 200
        assert resp.json()["request"] is None

    def test_ai_result_not_in_cleanup(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        resp = sapi(server_url, "post", "/debate/ai-result",
                   json={"merges": [], "cleaned": [], "new_arguments": []})
        assert resp.status_code == 400

    def test_ai_result_in_cleanup(self, server_url):
        sapi(server_url, "post", "/debate", json={"statement": "Test"})
        sapi(server_url, "post", "/debate/phase", json={"phase": "ai_cleanup"})
        resp = sapi(server_url, "post", "/debate/ai-result",
                   json={"merges": [], "cleaned": [], "new_arguments": [
                       {"side": "for", "text": "AI-generated argument"}
                   ]})
        assert resp.status_code == 200
