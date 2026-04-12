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

    # Get or create a TracerProvider
    provider = trace.get_tracer_provider()
    # If opentelemetry-instrument is active, provider is already a TracerProvider
    # Just add our file exporter as an additional processor
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(SimpleSpanProcessor(FileSpanExporter(traces_file)))
    else:
        # No auto-instrumentation — create our own provider
        new_provider = TracerProvider()
        new_provider.add_span_processor(SimpleSpanProcessor(FileSpanExporter(traces_file)))
        trace.set_tracer_provider(new_provider)
