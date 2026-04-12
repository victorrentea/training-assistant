"""OpenTelemetry setup for daemon and Railway.

When OTEL_TRACES_FILE is set, configures tracing programmatically:
- Creates a TracerProvider with FileSpanExporter
- Instruments FastAPI and urllib automatically
- No need for the `opentelemetry-instrument` CLI wrapper

Call setup_tracing() once at startup, BEFORE creating FastAPI apps.
"""
import os


def setup_tracing():
    """Configure OTel tracing with FileSpanExporter if OTEL_TRACES_FILE is set."""
    traces_file = os.environ.get("OTEL_TRACES_FILE")
    if not traces_file:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from daemon.telemetry.file_exporter import FileSpanExporter

    service_name = os.environ.get("OTEL_SERVICE_NAME", "unknown")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(FileSpanExporter(traces_file)))
    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI (will instrument any app created after this)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor().instrument()
    except ImportError:
        pass

    # Auto-instrument urllib
    try:
        from opentelemetry.instrumentation.urllib import URLLibInstrumentor
        URLLibInstrumentor().instrument()
    except ImportError:
        pass
