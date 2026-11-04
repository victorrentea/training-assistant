"""The phone's battery, parked here so the Mac can read it from any network.

The phone reaches the Mac directly only on its hotspot, on the home Wi-Fi or over
Bluetooth. It pushes every change of its percentage, plus a keep-alive every 10
minutes; the Mac reads the last one. Kept in memory: a redeploy loses it only until
the next keep-alive.

Auth: the bridge's shared token, fail-closed, as `X-Bridge-Token`.
"""
import os
import secrets
import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

_latest: tuple[int, bool, float] | None = None


class PhoneBatteryReading(BaseModel):
    pct: int = Field(ge=0, le=100)
    charging: bool


def _check(token: str | None) -> None:
    expected = os.environ.get("TABLET_BRIDGE_TOKEN") or os.environ.get("BRIDGE_TOKEN") or ""
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="bad token")


@router.put("/api/phone-battery")
def put_phone_battery(reading: PhoneBatteryReading, x_bridge_token: str | None = Header(default=None)) -> dict:
    global _latest
    _check(x_bridge_token)
    _latest = (reading.pct, reading.charging, time.time())
    return {"ok": True}


@router.get("/api/phone-battery")
def get_phone_battery(x_bridge_token: str | None = Header(default=None)) -> dict:
    """`{"pct":63,"charging":false,"age_s":120}`, or `{"pct":-1}` until the phone reports."""
    _check(x_bridge_token)
    if _latest is None:
        return {"pct": -1}
    pct, charging, at = _latest
    return {"pct": pct, "charging": charging, "age_s": max(0, int(time.time() - at))}
