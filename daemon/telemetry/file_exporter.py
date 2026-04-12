"""FileSpanExporter — writes spans as JSONL to a file on disk."""
import json
import threading

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


def _span_to_dict(span) -> dict:
    """Convert an OTel ReadableSpan to a plain dict for JSONL export."""
    ctx = span.get_span_context()
    parent = span.parent
    resource = span.resource
    return {
        "name": span.name,
        "context": {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        },
        "parent_id": format(parent.span_id, "016x") if parent else "",
        "start_time": span.start_time,
        "end_time": span.end_time,
        "attributes": dict(span.attributes) if span.attributes else {},
        "resource": dict(resource.attributes) if resource else {},
    }


class FileSpanExporter(SpanExporter):
    """Append one JSON line per span to a file. Thread-safe."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()

    def export(self, spans):
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                for span in spans:
                    f.write(json.dumps(_span_to_dict(span)) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, _timeout_millis=None):
        return True
