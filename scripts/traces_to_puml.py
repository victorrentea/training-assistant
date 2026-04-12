"""Generate PlantUML sequence diagrams from OTel trace JSONL files.

Generic transformation rules:
1. Collapse proxy chains (A -> Railway -> Daemon becomes A -> Daemon)
2. Collapse broadcast relay (Daemon -> Railway -> Browser becomes Daemon -> Browser)
3. Participant names from service.name attribute
4. Arrow labels from span names
5. Skip internal spans (same service parent->child)
"""
import json
import sys
from pathlib import Path


def _load_spans(traces_path: str, family: str) -> list[dict]:
    spans = []
    for line in Path(traces_path).read_text().strip().split("\n"):
        if not line.strip():
            continue
        span = json.loads(line)
        attrs = span.get("attributes", {})
        if family and attrs.get("trace.family") != family:
            continue
        spans.append(span)
    return spans


def _service_name(span: dict) -> str:
    resource = span.get("resource", {})
    return resource.get("service.name", resource.get("service_name", "Unknown"))


def _span_id(span: dict) -> str:
    ctx = span.get("context", {})
    return ctx.get("span_id", span.get("span_id", ""))


def _parent_id(span: dict) -> str:
    return span.get("parent_id", span.get("parent_span_id", ""))


def _build_span_index(spans: list[dict]) -> dict[str, dict]:
    return {_span_id(s): s for s in spans if _span_id(s)}


def _extract_edges(spans: list[dict]) -> list[tuple[str, str, str, int]]:
    index = _build_span_index(spans)
    edges = []
    for span in spans:
        pid = _parent_id(span)
        if not pid or pid not in index:
            continue
        parent = index[pid]
        from_svc = _service_name(parent)
        to_svc = _service_name(span)
        if from_svc == to_svc:
            continue
        label = span.get("name", "unknown")
        start = span.get("start_time", 0)
        edges.append((from_svc, to_svc, label, start))
    return edges


def _collapse_proxy(edges: list[tuple]) -> list[tuple]:
    result = []
    skip = set()
    for i, (f, t, label, ts) in enumerate(edges):
        if i in skip:
            continue
        if t == "Railway" and label == "proxy_request":
            for j in range(i + 1, len(edges)):
                f2, t2, label2, ts2 = edges[j]
                if f2 == "Railway" and t2 == "Daemon":
                    result.append((f, "Daemon", label2, ts))
                    skip.add(j)
                    break
            else:
                result.append((f, t, label, ts))
        else:
            result.append((f, t, label, ts))
    return result


def _collapse_broadcast(edges: list[tuple]) -> list[tuple]:
    result = []
    skip = set()
    for i, (f, t, label, ts) in enumerate(edges):
        if i in skip:
            continue
        if f == "Daemon" and t == "Railway" and "broadcast" in label:
            for j in range(i + 1, len(edges)):
                f2, t2, label2, ts2 = edges[j]
                if f2 == "Railway" and t2 not in ("Daemon", "Railway"):
                    result.append(("Daemon", t2, label, ts))
                    skip.add(j)
                    break
            else:
                result.append((f, t, label, ts))
        else:
            result.append((f, t, label, ts))
    return result


def _deduplicate_edges(edges: list[tuple]) -> list[tuple]:
    seen = set()
    result = []
    for f, t, label, ts in edges:
        key = (f, t, label)
        if key not in seen:
            seen.add(key)
            result.append((f, t, label, ts))
    return result


def generate_puml(traces_path: str, family: str, output: str) -> None:
    spans = _load_spans(traces_path, family)
    if not spans:
        Path(output).write_text(
            "@startuml\nnote over Daemon: No traces found for family '{}'\n@enduml\n".format(family)
        )
        return

    edges = _extract_edges(spans)
    edges.sort(key=lambda e: e[3])
    edges = _collapse_proxy(edges)
    edges = _collapse_broadcast(edges)
    edges = _deduplicate_edges(edges)

    participants = []
    seen_p = set()
    for f, t, _, _ in edges:
        for p in (f, t):
            if p not in seen_p:
                seen_p.add(p)
                participants.append(p)

    lines = ["@startuml"]
    lines.append("hide footbox")
    lines.append("")
    for p in participants:
        lines.append(f'participant "{p}"')
    lines.append("")
    for f, t, label, _ in edges:
        lines.append(f'"{f}" -> "{t}": {label}')
    lines.append("")
    lines.append("@enduml")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: traces_to_puml.py <traces.jsonl> <family> <output.puml>")
        sys.exit(1)
    generate_puml(sys.argv[1], sys.argv[2], sys.argv[3])
