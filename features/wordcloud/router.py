from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import require_host_auth
from core.messaging import broadcast_state
from core.state import state

router = APIRouter()


class WordcloudTopic(BaseModel):
    topic: str


@router.post("/wordcloud/topic", dependencies=[Depends(require_host_auth)])
async def set_wordcloud_topic(body: WordcloudTopic):
    state.wordcloud_topic = body.topic.strip()
    await broadcast_state()
    return {"ok": True}


@router.post("/wordcloud/clear", dependencies=[Depends(require_host_auth)])
async def clear_wordcloud():
    state.wordcloud_words = {}
    state.wordcloud_word_order = []
    state.wordcloud_topic = ""
    await broadcast_state()
    return {"ok": True}
