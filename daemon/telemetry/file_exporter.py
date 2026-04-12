"""FileSpanExporter — writes spans as JSONL to a file on disk."""
import threading

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class FileSpanExporter(SpanExporter):
    """Append one JSON line per span to a file. Thread-safe."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()

    def export(self, spans):
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                for span in spans:
                    f.write(span.to_json() + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, _timeout_millis=None):
        return True
