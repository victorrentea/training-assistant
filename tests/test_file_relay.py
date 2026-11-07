"""Tests for the encrypted file relay on Railway (railway/features/bridge/file_relay)."""
import pytest
from starlette.testclient import TestClient

from railway.app import app
import railway.features.bridge.file_relay as file_relay

TOKEN = "test-bridge-token"
AUTH = {"X-Bridge-Token": TOKEN}
ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def bridge_env(monkeypatch):
    monkeypatch.setenv("BRIDGE_TOKEN", TOKEN)
    monkeypatch.delenv("TABLET_BRIDGE_TOKEN", raising=False)
    file_relay._files.clear()


client = TestClient(app)


def test_a_file_goes_through_and_is_gone_once_taken():
    assert client.put(f"/api/file/{ID}", headers=AUTH, content=b"sealed").json() == {"size": 6}
    assert client.get(f"/api/file/{ID}/state", headers=AUTH).json() == {"state": "waiting"}
    assert client.get(f"/api/file/{ID}", headers=AUTH).content == b"sealed"
    client.delete(f"/api/file/{ID}", headers=AUTH)
    assert client.get(f"/api/file/{ID}/state", headers=AUTH).json() == {"state": "taken"}
    assert client.get(f"/api/file/{ID}", headers=AUTH).status_code == 404


def test_an_unknown_file_is_gone():
    assert client.get(f"/api/file/{ID}/state", headers=AUTH).json() == {"state": "gone"}
    assert client.get(f"/api/file/{ID}", headers=AUTH).status_code == 404


def test_a_file_over_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(file_relay, "MAX_FILE", 4)
    assert client.put(f"/api/file/{ID}", headers=AUTH, content=b"12345").status_code == 413
    assert client.get(f"/api/file/{ID}/state", headers=AUTH).json() == {"state": "gone"}


def test_the_total_held_is_limited(monkeypatch):
    monkeypatch.setattr(file_relay, "MAX_TOTAL", 8)
    assert client.put(f"/api/file/{ID}", headers=AUTH, content=b"123456").status_code == 200
    other = "f" * 32
    assert client.put(f"/api/file/{other}", headers=AUTH, content=b"123").status_code == 413


def test_an_old_file_expires(monkeypatch):
    client.put(f"/api/file/{ID}", headers=AUTH, content=b"sealed")
    monkeypatch.setattr(file_relay, "TTL_S", -1)
    assert client.get(f"/api/file/{ID}", headers=AUTH).status_code == 404


def test_strangers_are_kept_out():
    assert client.put(f"/api/file/{ID}", content=b"x").status_code in (401, 403)
    assert client.get(f"/api/file/{ID}", headers={"X-Bridge-Token": "wrong"}).status_code in (401, 403)


def test_an_id_cannot_be_a_path():
    assert client.get("/api/file/..%2Fsecret", headers=AUTH).status_code == 404
    assert client.put("/api/file/ABC", headers=AUTH, content=b"x").status_code == 422
