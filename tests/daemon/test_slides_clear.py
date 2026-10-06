"""Host "Clear slides": wipes the talk's shown-slides state and tells phones."""
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc.router import host_router
from daemon.misc.state import misc_state
from daemon.ws_messages import SlidesClearedMsg, SlidesHistoryCountUpdatedMsg


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


def test_clear_slides_resets_state_and_broadcasts():
    misc_state.current_slide = {"slug": "talk", "page": 7}
    misc_state.slides_viewed = [{"slug": "talk", "page": 7, "seconds": 30}]
    misc_state.slide_timeline = [{"slug": "talk", "page": 7, "seconds": 30, "at": "x"}]
    misc_state.slides_cleared = False
    try:
        with patch("daemon.misc.router.broadcast") as broadcast:
            resp = _client().post("/api/cur/host/slides/clear")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert misc_state.current_slide is None
        assert misc_state.slides_viewed == []
        assert misc_state.slide_timeline == []
        assert misc_state.slides_cleared is True
        sent = [c.args[0] for c in broadcast.call_args_list]
        assert any(isinstance(m, SlidesClearedMsg) for m in sent)
        assert any(isinstance(m, SlidesHistoryCountUpdatedMsg) and m.count == 0 for m in sent)
    finally:
        misc_state.current_slide = None
        misc_state.slides_viewed = []
        misc_state.slide_timeline = []
        misc_state.slides_cleared = False


def test_slides_cleared_msg_type():
    assert SlidesClearedMsg().model_dump() == {"type": "slides_cleared"}
