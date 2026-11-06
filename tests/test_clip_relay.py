"""Tests for the encrypted clipboard mailbox on Railway (railway/features/bridge/clip_relay)."""
import pytest
from starlette.testclient import TestClient

from railway.app import app
import railway.features.bridge.clip_relay as clip_relay

TOKEN = "test-bridge-token"
AUTH = {"X-Bridge-Token": TOKEN}


@pytest.fixture(autouse=True)
def bridge_env(monkeypatch):
    monkeypatch.setenv("BRIDGE_TOKEN", TOKEN)
    monkeypatch.delenv("TABLET_BRIDGE_TOKEN", raising=False)
    clip_relay._boxes.update(mac=clip_relay._Box(), phone=clip_relay._Box())


client = TestClient(app)


def test_a_clip_reaches_only_its_recipient():
    assert client.put("/api/clip/phone", headers=AUTH, json={"ciphertext": "abc"}).json() == {"seq": 1}
    assert client.get("/api/clip/phone", headers=AUTH).json() == {"seq": 1, "ciphertext": "abc"}
    assert client.get("/api/clip/mac", headers=AUTH).json()["ciphertext"] is None


def test_the_newest_clip_replaces_the_older_one():
    client.put("/api/clip/mac", headers=AUTH, json={"ciphertext": "old"})
    client.put("/api/clip/mac", headers=AUTH, json={"ciphertext": "new"})
    assert client.get("/api/clip/mac", headers=AUTH).json() == {"seq": 2, "ciphertext": "new"}


def test_a_seen_clip_is_not_news():
    client.put("/api/clip/mac", headers=AUTH, json={"ciphertext": "abc"})
    assert client.get("/api/clip/mac?after=1", headers=AUTH).json() == {"seq": 1, "ciphertext": None}


def test_a_restarted_server_still_delivers_to_a_reader_with_a_higher_seq():
    client.put("/api/clip/mac", headers=AUTH, json={"ciphertext": "abc"})
    assert client.get("/api/clip/mac?after=40", headers=AUTH).json() == {"seq": 1, "ciphertext": "abc"}


def test_an_old_clip_expires(monkeypatch):
    client.put("/api/clip/mac", headers=AUTH, json={"ciphertext": "abc"})
    clip_relay._boxes["mac"].at -= clip_relay.TTL_S + 1
    assert client.get("/api/clip/mac", headers=AUTH).json()["ciphertext"] is None
    assert clip_relay._boxes["mac"].ciphertext is None


def test_a_bad_token_is_refused_both_ways():
    bad = {"X-Bridge-Token": "wrong"}
    assert client.put("/api/clip/mac", headers=bad, json={"ciphertext": "abc"}).status_code == 401
    assert client.get("/api/clip/mac", headers=bad).status_code == 401


def test_an_unknown_recipient_is_refused():
    assert client.put("/api/clip/tablet", headers=AUTH, json={"ciphertext": "abc"}).status_code == 422
