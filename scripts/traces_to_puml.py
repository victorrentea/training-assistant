"""Generate PlantUML sequence diagrams from OTel trace JSONL files.

Generic transformation rules:
1. Collapse proxy chains (A -> Railway -> Daemon becomes A -> Daemon)
2. Collapse broadcast relay (Daemon -> Railway -> Browser becomes Daemon -> Browser)
3. Participant names from service.name attribute
4. Arrow labels from span names
5. Skip internal spans (same service parent->child)
6. Infer host origin from /host/ path patterns in root daemon spans
7. Infer broadcast/notify targets from span name prefixes
"""
import json
import re
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


# Pattern: /api/{session_id}/host/... or /host/{session_id}
_HOST_PATH_RE = re.compile(r"(GET|POST|PUT|DELETE|PATCH) /.*host")


def _extract_edges(spans: list[dict]) -> list[tuple[str, str, str, int]]:
    """Extract (from_service, to_service, label, start_time) edges from spans."""
    index = _build_span_index(spans)
    edges = []
    for span in spans:
        name = span.get("name", "")
        svc = _service_name(span)
        start = span.get("start_time", 0)
        pid = _parent_id(span)

        # Rule 7: broadcast:* and notify_host:* root spans from Daemon
        if svc == "Daemon" and name.startswith("broadcast:"):
            msg_type = name.split(":", 1)[1]
            edges.append(("Daemon", "Participant", f"broadcast {msg_type}", start))
            continue
        if svc == "Daemon" and name.startswith("notify_host:"):
            msg_type = name.split(":", 1)[1]
            edges.append(("Daemon", "Host", f"notify_host {msg_type}", start))
            continue

        # Rule 6: Daemon root HTTP spans with /host/ path => Host -> Daemon
        if svc == "Daemon" and (not pid or pid not in index):
            if _HOST_PATH_RE.match(name):
                edges.append(("Host", "Daemon", name, start))
                continue

        # Standard: cross-service parent->child edge
        if not pid or pid not in index:
            continue
        parent = index[pid]
        from_svc = _service_name(parent)
        to_svc = _service_name(span)
        if from_svc == to_svc:
            continue  # Rule 5: skip internal spans
        label = name or "unknown"
        edges.append((from_svc, to_svc, label, start))
    return edges


def _collapse_proxy(edges: list[tuple]) -> list[tuple]:
    """Rule 1: Railway->Daemon edges for participant API calls become Participant->Daemon.

    Railway proxies all participant REST traffic to the daemon. When the trace shows
    Railway->Daemon for a /participant/ or /api/participant/ path, replace Railway
    with Participant to show the logical caller.

    Also handles the explicit proxy_request pattern: A->Railway(proxy_request)->Daemon
    collapses to A->Daemon.
    """
    result = []
    skip = set()
    for i, (f, t, label, ts) in enumerate(edges):
        if i in skip:
            continue
        # Explicit proxy_request pattern
        if t == "Railway" and label == "proxy_request":
            for j in range(i + 1, len(edges)):
                f2, t2, label2, ts2 = edges[j]
                if f2 == "Railway" and t2 == "Daemon":
                    source = "Participant" if f == "Railway" else f
                    result.append((source, "Daemon", label2, ts))
                    skip.add(j)
                    break
            else:
                result.append((f, t, label, ts))
        # Railway->Daemon with participant path => Participant->Daemon
        elif f == "Railway" and t == "Daemon" and "participant" in label.lower():
            result.append(("Participant", "Daemon", label, ts))
        else:
            result.append((f, t, label, ts))
    return result


def _collapse_broadcast(edges: list[tuple]) -> list[tuple]:
    """Rule 2: Collapse Daemon->Railway->Browser into Daemon->Browser for broadcasts."""
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
    """Remove duplicate (from, to, label) tuples, keeping first occurrence order."""
    seen = set()
    result = []
    for f, t, label, ts in edges:
        key = (f, t, label)
        if key not in seen:
            seen.add(key)
            result.append((f, t, label, ts))
    return result


def generate_puml(traces_path: str, family: str, output: str) -> None:
    """Generate a PlantUML sequence diagram from collected traces."""
    spans = _load_spans(traces_path, family)
    if not spans:
        Path(output).write_text(
            f"@startuml\nnote over Daemon: No traces found for family '{family}'\n@enduml\n"
        )
        return

    edges = _extract_edges(spans)
    edges.sort(key=lambda e: e[3])  # sort by start_time
    edges = _collapse_proxy(edges)
    edges = _collapse_broadcast(edges)
    edges = _deduplicate_edges(edges)

    # Collect participant names in order of first appearance
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
