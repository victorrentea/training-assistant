import json
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _make_span(name: str = "test-span"):
    """Build a minimal fake ReadableSpan compatible with _span_to_dict."""
    ctx = SimpleNamespace(trace_id=0xABC123, span_id=0xDEF456)
    return SimpleNamespace(
        name=name,
        get_span_context=lambda: ctx,
        parent=None,
        resource=None,
        start_time=0,
        end_time=1,
        attributes={},
    )


def test_file_exporter_writes_jsonl():
    from daemon.telemetry.file_exporter import FileSpanExporter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    exporter = FileSpanExporter(path)

    from opentelemetry.sdk.trace.export import SpanExportResult

    result = exporter.export([_make_span(), _make_span()])
    assert result == SpanExportResult.SUCCESS

    lines = Path(path).read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "test-span"


def test_file_exporter_appends_not_overwrites():
    from daemon.telemetry.file_exporter import FileSpanExporter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    exporter = FileSpanExporter(path)

    exporter.export([_make_span("first")])
    exporter.export([_make_span("second")])

    lines = Path(path).read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "first"
    assert json.loads(lines[1])["name"] == "second"
