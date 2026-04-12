"""OpenTelemetry setup for daemon and Railway.

When OTEL_TRACES_FILE is set, configures a FileSpanExporter that writes
spans to the specified JSONL file. Call setup_file_exporter() once at
startup to activate it.
"""
import os


def setup_file_exporter():
    """Configure OTel to export spans to OTEL_TRACES_FILE if set."""
    traces_file = os.environ.get("OTEL_TRACES_FILE")
    if not traces_file:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from daemon.telemetry.file_exporter import FileSpanExporter

    exporter = FileSpanExporter(traces_file)
    processor = SimpleSpanProcessor(exporter)

    # Get the active provider — may be a ProxyTracerProvider wrapping
    # the real one when opentelemetry-instrument is active.
    provider = trace.get_tracer_provider()

    # Try the provider directly
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(processor)
        return

    # ProxyTracerProvider wraps the real provider in _proxy_tracer_provider
    # or the real provider is accessible via the _real_provider attribute
    for attr in ("_proxy_tracer_provider", "_real_provider"):
        real = getattr(provider, attr, None)
        if real and hasattr(real, "add_span_processor"):
            real.add_span_processor(processor)
            return

    # Last resort: create our own provider
    new_provider = TracerProvider()
    new_provider.add_span_processor(processor)
    trace.set_tracer_provider(new_provider)
