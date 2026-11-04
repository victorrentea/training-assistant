"""Tests for the phone's battery parked on Railway (railway/features/bridge/phone_battery)."""
import pytest
from starlette.testclient import TestClient

from railway.app import app
import railway.features.bridge.phone_battery as phone_battery

TOKEN = "test-bridge-token"
AUTH = {"X-Bridge-Token": TOKEN}


@pytest.fixture(autouse=True)
def bridge_env(monkeypatch):
    monkeypatch.setenv("BRIDGE_TOKEN", TOKEN)
    monkeypatch.delenv("TABLET_BRIDGE_TOKEN", raising=False)
    phone_battery._latest = None
    yield
    phone_battery._latest = None


def test_unknown_until_the_phone_reports():
    assert TestClient(app).get("/api/phone-battery", headers=AUTH).json() == {"pct": -1}


def test_the_last_push_is_read_back_with_its_age():
    client = TestClient(app)
    assert client.put("/api/phone-battery", headers=AUTH, json={"pct": 63, "charging": True}).status_code == 200
    body = client.get("/api/phone-battery", headers=AUTH).json()
    assert body["pct"] == 63 and body["charging"] is True and body["age_s"] >= 0


@pytest.mark.parametrize("headers", [{}, {"X-Bridge-Token": "WRONG"}])
def test_both_sides_need_the_token(headers):
    client = TestClient(app)
    assert client.put("/api/phone-battery", headers=headers, json={"pct": 63, "charging": False}).status_code == 401
    assert client.get("/api/phone-battery", headers=headers).status_code == 401


def test_refused_when_no_token_is_configured(monkeypatch):
    monkeypatch.delenv("BRIDGE_TOKEN")
    assert TestClient(app).get("/api/phone-battery", headers=AUTH).status_code == 401


def test_an_impossible_level_is_refused():
    assert TestClient(app).put("/api/phone-battery", headers=AUTH, json={"pct": 140, "charging": False}).status_code == 422
