"""The clipboard between the Mac and the phone, when they have no shorter way.

Only ciphertext passes through here: both ends encrypt with a key this server never
sees. One box per recipient, holding the newest clip only, kept in memory for five
minutes and never logged. A redeploy loses at most a clip nobody picked up.

The reader long-polls: `after` is the last `seq` it saw, so a restart of this server,
which restarts `seq`, still counts as news.

Auth: the bridge's shared token, as `X-Bridge-Token`.
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from railway.features.bridge.phone_battery import _check

router = APIRouter()

TTL_S = 300
_POLL_S = 0.25

Recipient = Literal["mac", "phone"]


@dataclass
class _Box:
    seq: int = 0
    ciphertext: str | None = None
    at: float = 0.0


_boxes: dict[str, _Box] = {"mac": _Box(), "phone": _Box()}


class Clip(BaseModel):
    ciphertext: str = Field(min_length=1, max_length=256 * 1024)


@router.put("/api/clip/{to}")
def put_clip(to: Recipient, clip: Clip, x_bridge_token: str | None = Header(default=None)) -> dict:
    _check(x_bridge_token)
    box = _boxes[to]
    box.seq += 1
    box.ciphertext = clip.ciphertext
    box.at = time.time()
    return {"seq": box.seq}


def _news(to: str, after: int) -> dict | None:
    box = _boxes[to]
    if box.ciphertext is None or box.seq == after:
        return None
    if time.time() - box.at > TTL_S:
        box.ciphertext = None
        return None
    return {"seq": box.seq, "ciphertext": box.ciphertext}


@router.get("/api/clip/{to}")
async def get_clip(
    to: Recipient,
    after: int = -1,
    wait: float = Query(default=0, ge=0, le=50),
    x_bridge_token: str | None = Header(default=None),
) -> dict:
    """`{"seq":7,"ciphertext":"…"}`, or `{"seq":<after>,"ciphertext":null}` when `wait` runs out."""
    _check(x_bridge_token)
    deadline = time.monotonic() + wait
    while True:
        news = _news(to, after)
        if news is not None:
            return news
        if time.monotonic() >= deadline:
            return {"seq": after, "ciphertext": None}
        await asyncio.sleep(_POLL_S)
