import json
import tempfile
from pathlib import Path


def test_file_exporter_writes_jsonl():
    from daemon.telemetry.file_exporter import FileSpanExporter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    exporter = FileSpanExporter(path)

    class FakeSpan:
        def to_json(self):
            return json.dumps({"name": "test-span", "trace_id": "abc123"})

    from opentelemetry.sdk.trace.export import SpanExportResult

    result = exporter.export([FakeSpan(), FakeSpan()])
    assert result == SpanExportResult.SUCCESS

    lines = Path(path).read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "test-span"


def test_file_exporter_appends_not_overwrites():
    from daemon.telemetry.file_exporter import FileSpanExporter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    exporter = FileSpanExporter(path)

    class FakeSpan:
        def __init__(self, name):
            self._name = name
        def to_json(self):
            return json.dumps({"name": self._name})

    exporter.export([FakeSpan("first")])
    exporter.export([FakeSpan("second")])

    lines = Path(path).read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "first"
    assert json.loads(lines[1])["name"] == "second"
