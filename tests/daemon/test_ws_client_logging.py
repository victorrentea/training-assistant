from daemon.ws_client import DaemonWsClient


class TestWsClientLogging:
    def test_suppresses_proxy_request_and_proxy_response_traces(self):
        assert not DaemonWsClient._should_trace_msg({"type": "proxy_request"})
        assert not DaemonWsClient._should_trace_msg({"type": "proxy_response"})

    def test_suppresses_slide_log_traces(self):
        assert not DaemonWsClient._should_trace_msg({"type": "slide_log"})

    def test_keeps_other_message_types_visible(self):
        assert DaemonWsClient._should_trace_msg({"type": "broadcast"})
