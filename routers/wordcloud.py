from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast, build_state_message
from state import state

router = APIRouter()


class WordcloudTopic(BaseModel):
    topic: str


@router.post("/api/wordcloud/topic", dependencies=[Depends(require_host_auth)])
async def set_wordcloud_topic(body: WordcloudTopic):
    state.wordcloud_topic = body.topic.strip()
    await broadcast(build_state_message())
    return {"ok": True}


@router.post("/api/wordcloud/clear", dependencies=[Depends(require_host_auth)])
async def clear_wordcloud():
    state.wordcloud_words = {}
    state.wordcloud_topic = ""
    await broadcast(build_state_message())
    return {"ok": True}
