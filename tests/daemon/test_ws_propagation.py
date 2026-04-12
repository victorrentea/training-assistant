from daemon.telemetry.ws_propagation import extract_trace_context, inject_trace_context


def test_inject_adds_traceparent_to_dict():
    """inject_trace_context adds _traceparent to a dict when a span is active."""
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    msg = {"type": "poll_opened", "poll": {}}
    with tracer.start_as_current_span("test-span"):
        inject_trace_context(msg)

    assert "_traceparent" in msg
    assert msg["_traceparent"].startswith("00-")
    provider.shutdown()


def test_inject_is_noop_without_active_span():
    """inject_trace_context does nothing when no span is active."""
    msg = {"type": "test"}
    inject_trace_context(msg)
    assert "_traceparent" not in msg


def test_extract_returns_context_from_traceparent():
    """extract_trace_context returns a context from _traceparent field."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    msg = {}
    with tracer.start_as_current_span("parent"):
        inject_trace_context(msg)

    ctx = extract_trace_context(msg)
    assert ctx is not None

    span_ctx = trace.get_current_span(ctx).get_span_context()
    assert span_ctx.trace_id != 0
    provider.shutdown()


def test_extract_returns_none_without_traceparent():
    """extract_trace_context returns None when _traceparent is absent."""
    ctx = extract_trace_context({"type": "test"})
    assert ctx is None
