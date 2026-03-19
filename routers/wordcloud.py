from fastapi import APIRouter, Depends

from auth import require_host_auth
from messaging import broadcast, build_state_message
from state import state

router = APIRouter()


@router.post("/api/wordcloud/clear", dependencies=[Depends(require_host_auth)])
async def clear_wordcloud():
    state.wordcloud_words = {}
    await broadcast(build_state_message())
    return {"ok": True}
