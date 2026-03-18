from fastapi import APIRouter, Depends, HTTPException

from auth import require_host_auth
from pydantic import BaseModel

from messaging import broadcast, build_state_message
from state import state, ActivityType

router = APIRouter()


class WordCloudStatus(BaseModel):
    active: bool


@router.post("/api/wordcloud/status", dependencies=[Depends(require_host_auth)])
async def set_wordcloud_status(body: WordCloudStatus):
    if body.active:
        if state.current_activity != ActivityType.NONE:
            raise HTTPException(409, "Another activity is already active")
        state.current_activity = ActivityType.WORDCLOUD
        state.wordcloud_words = {}
    else:
        state.current_activity = ActivityType.NONE
    await broadcast(build_state_message())
    return {"ok": True}
