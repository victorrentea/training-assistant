import json
import tempfile
from pathlib import Path


def _write_spans(path, spans):
    Path(path).write_text("\n".join(json.dumps(s) for s in spans) + "\n")


def _make_span(name, service, trace_id="aaa", span_id="s1", parent_span_id="",
               attributes=None, start_time=1000, end_time=2000):
    return {
        "name": name,
        "resource": {"service.name": service},
        "context": {"trace_id": trace_id, "span_id": span_id},
        "parent_id": parent_span_id,
        "start_time": start_time,
        "end_time": end_time,
        "attributes": attributes or {},
    }


def test_basic_cross_service_arrows():
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/poll/vote", "Participant", span_id="s1",
                    start_time=1000, attributes={"trace.family": "poll"}),
        _make_span("POST /api/poll/vote", "Daemon", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"trace.family": "poll"}),
    ])

    generate_puml(path, family="poll", output=out)
    content = Path(out).read_text()

    assert "Participant" in content
    assert "Daemon" in content
    assert "POST /api/poll/vote" in content
    assert "@startuml" in content
    assert "@enduml" in content


def test_skip_internal_spans():
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/poll", "Host", span_id="s1",
                    start_time=1000, attributes={"trace.family": "test"}),
        _make_span("POST /api/poll", "Daemon", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"trace.family": "test"}),
        _make_span("create_poll", "Daemon", span_id="s3", parent_span_id="s2",
                    start_time=1002, attributes={"trace.family": "test"}),
    ])

    generate_puml(path, family="test", output=out)
    content = Path(out).read_text()

    assert "create_poll" not in content
    assert "POST /api/poll" in content


def test_collapse_proxy_chain():
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/participant/poll/vote", "Participant", span_id="s1",
                    start_time=1000, attributes={"trace.family": "proxy"}),
        _make_span("proxy_request", "Railway", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"proxy.path": "/api/participant/poll/vote",
                                                  "trace.family": "proxy"}),
        _make_span("POST /api/participant/poll/vote", "Daemon", span_id="s3", parent_span_id="s2",
                    start_time=1002, attributes={"trace.family": "proxy"}),
    ])

    generate_puml(path, family="proxy", output=out)
    content = Path(out).read_text()

    assert "Railway" not in content
    assert "Participant" in content
    assert "Daemon" in content


def test_collapse_proxy_chain_railway_source():
    """When Railway is the proxy source (no browser span), rename to Participant."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/participant/poll/vote", "Railway", span_id="s1",
                    start_time=1000),
        _make_span("proxy_request", "Railway", span_id="s2", parent_span_id="s1",
                    start_time=1001),
        _make_span("POST /api/participant/poll/vote", "Daemon", span_id="s3", parent_span_id="s2",
                    start_time=1002),
    ])

    generate_puml(path, family="", output=out)
    content = Path(out).read_text()

    # The proxy chain collapses to Participant→Daemon (Railway is just a proxy)
    assert "Participant" in content
    assert "Daemon" in content
    assert '"Participant" -> "Daemon"' in content or '"Participant" ->' in content


def test_infer_host_origin():
    """Daemon root spans with /host/ path become Host -> Daemon arrows."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/{session_id}/host/poll", "Daemon", span_id="s1",
                    start_time=1000),
        _make_span("POST /api/{session_id}/host/poll/open", "Daemon", span_id="s2",
                    start_time=2000),
    ])

    generate_puml(path, family="", output=out)
    content = Path(out).read_text()

    assert "Host" in content
    assert "Daemon" in content
    assert "POST /api/{session_id}/host/poll" in content


def test_infer_broadcast_target():
    """broadcast:* spans produce Daemon -> Participant arrows."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("broadcast:poll_opened", "Daemon", span_id="s1", start_time=1000),
    ])

    generate_puml(path, family="", output=out)
    content = Path(out).read_text()

    assert "Daemon" in content
    assert "Participant" in content
    assert "poll_opened" in content


def test_infer_notify_host_target():
    """notify_host:* spans produce Daemon -> Host arrows."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("notify_host:poll_ai_generated", "Daemon", span_id="s1", start_time=1000),
    ])

    generate_puml(path, family="", output=out)
    content = Path(out).read_text()

    assert "Daemon" in content
    assert "Host" in content
    assert "poll_ai_generated" in content


def test_collapse_broadcast_relay():
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("broadcast:poll_opened", "Daemon", span_id="s1",
                    start_time=1000, attributes={"trace.family": "bcast"}),
        _make_span("broadcast_fanout", "Railway", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"trace.family": "bcast"}),
        _make_span("ws_receive:poll_opened", "Participant", span_id="s3", parent_span_id="s2",
                    start_time=1002, attributes={"trace.family": "bcast"}),
    ])

    generate_puml(path, family="bcast", output=out)
    content = Path(out).read_text()

    assert "Railway" not in content
    assert "Daemon" in content
    assert "Participant" in content


def test_given_phase_renders_gray():
    """Spans with bdd.phase=given produce gray arrows."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/participant/poll/vote", "Participant", span_id="s1",
                    start_time=1000, attributes={"bdd.phase": "given"}),
        _make_span("POST /api/participant/poll/vote", "Daemon", span_id="s2", parent_span_id="s1",
                    start_time=1001, attributes={"bdd.phase": "given"}),
        _make_span("broadcast:poll_opened", "Daemon", span_id="s3",
                    start_time=2000, attributes={"bdd.phase": "when"}),
    ])

    generate_puml(path, family="", output=out)
    content = Path(out).read_text()

    # Given phase arrow should be gray
    assert "[#gray]" in content
    # When phase arrow should NOT be gray (broadcast prefix removed, just "poll_opened")
    lines = content.split("\n")
    broadcast_line = [line for line in lines if "poll_opened" in line][0]
    assert "[#gray]" not in broadcast_line


def test_no_phase_renders_default():
    """Spans without bdd.phase produce default (black) arrows."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        _make_span("POST /api/poll/vote", "Participant", span_id="s1", start_time=1000),
        _make_span("POST /api/poll/vote", "Daemon", span_id="s2", parent_span_id="s1", start_time=1001),
    ])

    generate_puml(path, family="", output=out)
    content = Path(out).read_text()

    assert "[#gray]" not in content


def test_scenarios_parameter_colors_by_trace_id():
    """scenarios parameter colors edges by timestamp boundaries and adds separators."""
    from scripts.traces_to_puml import generate_puml

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    out = path + ".puml"

    _write_spans(path, [
        # Given-phase spans (before when_start_ns=1500)
        _make_span("POST /api/participant/register", "Participant", span_id="s1",
                    start_time=1000),
        _make_span("POST /api/participant/register", "Daemon", span_id="s2", parent_span_id="s1",
                    start_time=1001),
        # When-phase spans (after when_start_ns=1500)
        _make_span("broadcast:slides_cache_status", "Daemon", span_id="s3",
                    start_time=2000),
    ])

    scenarios = [{"name": "Open slide", "when_start_ns": 1500, "end_ns": 3000}]
    generate_puml(path, family="", output=out, scenarios=scenarios)
    content = Path(out).read_text()

    # Given-phase arrow should be gray
    register_line = [line for line in content.split("\n") if "register" in line][0]
    assert "[#gray]" in register_line
    # When-phase arrow should NOT be gray
    broadcast_line = [line for line in content.split("\n") if "slides_cache_status" in line][0]
    assert "[#gray]" not in broadcast_line
    # Scenario separator should be present
    assert "== Open slide ==" in content
