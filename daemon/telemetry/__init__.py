"""OpenTelemetry setup for daemon and Railway.

When OTEL_TRACES_FILE is set, configures tracing programmatically:
- Creates a TracerProvider with FileSpanExporter
- Call setup_tracing() once at startup

FastAPI app instrumentation should be done separately per-app
via instrument_fastapi_app(app).
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


def instrument_fastapi_app(app):
    """Instrument a specific FastAPI app instance for OTel tracing."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass


def instrument_urllib():
    """Instrument urllib so outgoing HTTP calls (e.g. daemon→Railway) generate spans."""
    try:
        from opentelemetry.instrumentation.urllib import URLLibInstrumentor
        URLLibInstrumentor().instrument()
    except ImportError:
        pass
