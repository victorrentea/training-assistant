"""Tests for participant name sanitization (fix #1) and dedup normalization (fix #2).

Covers the shared ``sanitize_name`` / ``normalize_for_dedup`` helpers directly,
then their wiring through the register/rename endpoints.
"""
import unicodedata

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import patch

from daemon.participant.router import router
from daemon.participant.sanitize import (
    MAX_NAME_LEN,
    normalize_for_dedup,
    sanitize_name,
)
from daemon.participant.state import ParticipantState


# ── Unit: sanitize_name (fix #1) ──────────────────────────────────────────────

class TestSanitizeName:
    def test_empty_and_none(self):
        assert sanitize_name(None) == ""
        assert sanitize_name("") == ""
        assert sanitize_name("    ") == ""

    def test_strips_newlines_and_carriage_returns(self):
        out = sanitize_name("Alice\nBob\r\nCarol")
        assert "\n" not in out and "\r" not in out
        assert out == "Alice Bob Carol"  # folded to single spaces

    def test_strips_nul_and_control_chars(self):
        out = sanitize_name("Al\x00ice\x07\x1f")
        assert out == "Alice"
        assert all(ord(ch) >= 0x20 for ch in out)

    def test_strips_ansi_escape_sequences_whole(self):
        # The full CSI sequence is removed — no printable "[31m" tail left behind.
        out = sanitize_name("\x1b[31mRed\x1b[0m Name")
        assert out == "Red Name"
        assert "[31m" not in out and "\x1b" not in out

    def test_strips_bidi_override_chars(self):
        # RLO (U+202E) is a spoofing vector — must be removed.
        out = sanitize_name("Alice‮ecilA")
        assert "‮" not in out
        out2 = sanitize_name("⁦a⁩b‪c")  # isolates + LRE
        assert all(ord(ch) not in range(0x2066, 0x206A) for ch in out2)
        assert "‪" not in out2

    def test_collapses_internal_whitespace(self):
        assert sanitize_name("Alice    B    Carol") == "Alice B Carol"
        assert sanitize_name("Alice\t\tBob") == "Alice Bob"

    def test_nfc_normalizes(self):
        # NFD "José" (e + combining acute) → NFC single-codepoint é.
        nfd = "José"
        out = sanitize_name(nfd)
        assert out == unicodedata.normalize("NFC", "José")
        assert out == "José"

    def test_length_cap_applied_after_sanitization(self):
        # Control-char padding must not let a name smuggle past the 64 cap.
        raw = "A" * 100
        assert len(sanitize_name(raw)) == MAX_NAME_LEN
        padded = "\x00" * 50 + "B" * 70
        assert len(sanitize_name(padded)) == MAX_NAME_LEN

    def test_exactly_64_survives(self):
        name = "A" * 64
        assert sanitize_name(name) == name

    def test_preserves_normal_unicode_name(self):
        assert sanitize_name("Ada Lovelace") == "Ada Lovelace"
        assert sanitize_name("François") == "François"


# ── Unit: normalize_for_dedup (fix #2) ────────────────────────────────────────

class TestNormalizeForDedup:
    def test_casefold_matches(self):
        assert normalize_for_dedup("Alice") == normalize_for_dedup("alice")
        assert normalize_for_dedup("ALICE") == normalize_for_dedup("alice")

    def test_nfc_vs_nfd_jose_match(self):
        assert normalize_for_dedup("José") == normalize_for_dedup("José")

    def test_double_space_matches_single(self):
        assert normalize_for_dedup("Ada  Lovelace") == normalize_for_dedup("Ada Lovelace")

    def test_distinct_names_differ(self):
        assert normalize_for_dedup("Alice") != normalize_for_dedup("Bob")

    def test_empty(self):
        assert normalize_for_dedup(None) == ""
        assert normalize_for_dedup("   ") == ""


# ── Integration: sanitization + dedup through the endpoints ───────────────────

@pytest.fixture
def fresh_state():
    ps = ParticipantState()
    ps.mode = "workshop"
    with patch("daemon.participant.router.participant_state", ps):
        yield ps


@pytest.fixture
def client(fresh_state):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRegisterSanitizes:
    def test_register_strips_control_chars_before_store(self, client, fresh_state):
        resp = client.post(
            "/api/participant/register",
            json={"name": "Ev\x00il\nName"},
            headers={"X-Participant-ID": "u1"},
        )
        assert resp.status_code == 200
        stored = fresh_state.participant_names["u1"]
        assert "\x00" not in stored and "\n" not in stored
        assert stored == "Evil Name"
        assert resp.json()["name"] == "Evil Name"

    def test_all_noise_name_falls_through_to_auto_assign(self, client, fresh_state):
        # An all-control-char name sanitizes to "" → treated as anonymous join.
        resp = client.post(
            "/api/participant/register",
            json={"name": "\x00\x1b[0m\n\r"},
            headers={"X-Participant-ID": "u1"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"]  # got an auto-assigned name
        assert "u1" in fresh_state.anonymous_pids  # anonymous signal set

    def test_rename_strips_bidi_override(self, client, fresh_state):
        fresh_state.participant_names["u1"] = "Gandalf"
        resp = client.put(
            "/api/participant/name",
            json={"name": "Al‮ice"},
            headers={"X-Participant-ID": "u1"},
        )
        assert resp.status_code == 200
        assert "‮" not in fresh_state.participant_names["u1"]


class TestDuplicateNormalization:
    def test_case_insensitive_duplicate_flagged(self, client, fresh_state):
        fresh_state.participant_names["u1"] = "Alice"
        resp = client.post(
            "/api/participant/register",
            json={"name": "alice"},
            headers={"X-Participant-ID": "u2"},
        )
        assert resp.status_code == 200
        assert resp.json()["name_conflict"] is True

    def test_nfd_vs_nfc_duplicate_flagged(self, client, fresh_state):
        fresh_state.participant_names["u1"] = "José"  # stored NFC
        resp = client.post(
            "/api/participant/register",
            json={"name": "José"},  # NFD input (sanitized to NFC)
            headers={"X-Participant-ID": "u2"},
        )
        assert resp.status_code == 200
        assert resp.json()["name_conflict"] is True

    def test_double_space_duplicate_flagged(self, client, fresh_state):
        fresh_state.participant_names["u1"] = "Ada Lovelace"
        resp = client.post(
            "/api/participant/register",
            json={"name": "Ada  Lovelace"},  # collapses to single space
            headers={"X-Participant-ID": "u2"},
        )
        assert resp.status_code == 200
        assert resp.json()["name_conflict"] is True

    def test_distinct_names_no_conflict(self, client, fresh_state):
        fresh_state.participant_names["u1"] = "Alice"
        resp = client.post(
            "/api/participant/register",
            json={"name": "Bob"},
            headers={"X-Participant-ID": "u2"},
        )
        assert resp.json()["name_conflict"] is False
