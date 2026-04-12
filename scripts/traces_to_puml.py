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


def _extract_edges(spans: list[dict]) -> list[tuple[str, str, str, int, str, str, bool]]:
    """Extract edges from spans.

    Returns (from_svc, to_svc, label, start_time, bdd_phase, trace_id, is_async).
    is_async=True for broadcast/notify_host (rendered as dashed arrows).
    """
    index = _build_span_index(spans)
    edges = []
    for span in spans:
        name = span.get("name", "")
        svc = _service_name(span)
        start = span.get("start_time", 0)
        pid = _parent_id(span)
        phase = span.get("attributes", {}).get("bdd.phase", "")
        tid = span.get("context", {}).get("trace_id", "")

        # Rule 7: broadcast:* and notify_host:* root spans from Daemon
        if svc == "Daemon" and name.startswith("broadcast:"):
            msg_type = name.split(":", 1)[1]
            edges.append(("Daemon", "Participant", msg_type, start, phase, tid, True))
            continue
        if svc == "Daemon" and name.startswith("notify_host:"):
            msg_type = name.split(":", 1)[1]
            edges.append(("Daemon", "Host", msg_type, start, phase, tid, True))
            continue

        # Rule 6: Daemon root HTTP spans with /host/ path => Host -> Daemon
        if svc == "Daemon" and (not pid or pid not in index):
            if _HOST_PATH_RE.match(name):
                edges.append(("Host", "Daemon", name, start, phase, tid, False))
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
        edges.append((from_svc, to_svc, label, start, phase, tid, False))
    return edges


def _collapse_proxy(edges: list[tuple]) -> list[tuple]:
    """Rule 1: Railway->Daemon edges become Participant->Daemon (Railway is a proxy)."""
    result = []
    skip = set()
    for i, e in enumerate(edges):
        f, t, label, ts, phase, tid, is_async = e
        if i in skip:
            continue
        if t == "Railway" and label == "proxy_request":
            for j in range(i + 1, len(edges)):
                e2 = edges[j]
                if e2[0] == "Railway" and e2[1] == "Daemon":
                    source = "Participant" if f == "Railway" else f
                    result.append((source, "Daemon", e2[2], ts, phase, tid, is_async))
                    skip.add(j)
                    break
            else:
                result.append(e)
        elif f == "Railway" and t == "Daemon":
            result.append(("Participant", "Daemon", label, ts, phase, tid, is_async))
        else:
            result.append(e)
    return result


def _collapse_broadcast(edges: list[tuple]) -> list[tuple]:
    """Rule 2: Collapse Daemon->Railway->Browser into Daemon->Browser for broadcasts."""
    result = []
    skip = set()
    for i, e in enumerate(edges):
        f, t, label = e[0], e[1], e[2]
        if i in skip:
            continue
        if f == "Daemon" and t == "Railway" and "broadcast" in label:
            for j in range(i + 1, len(edges)):
                e2 = edges[j]
                if e2[0] == "Railway" and e2[1] not in ("Daemon", "Railway"):
                    result.append(("Daemon", e2[1], label, e[3], e[4], e[5], e[6]))
                    skip.add(j)
                    break
            else:
                result.append(e)
        else:
            result.append(e)
    return result


def _deduplicate_edges(edges: list[tuple]) -> list[tuple]:
    """Remove duplicate (from, to, label) tuples, keeping first occurrence order."""
    seen = set()
    result = []
    for e in edges:
        key = (e[0], e[1], e[2])  # (from, to, label)
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def generate_puml(traces_path: str, family: str, output: str,
                  scenarios: list[dict] | None = None) -> None:
    """Generate a PlantUML sequence diagram from collected traces.

    scenarios: optional list of scenario descriptors, each with:
        - name: str (scenario title, rendered as PlantUML separator)
        - when_trace_ids: set[str] (trace IDs captured from browser requests
          during When/Then phases — edges matching these are black, rest gray)
        - end_ns: int (nanosecond timestamp when scenario ended)
    """
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
    if not scenarios:
        edges = _deduplicate_edges(edges)

    # Assign phases from scenario timestamp boundaries
    if scenarios:
        phased = []
        for e in edges:
            f, t, label, ts, phase, tid, is_async = e
            if not phase:
                phase = "given"
                for sc in scenarios:
                    when_ns = sc.get("when_start_ns", 0)
                    end_ns = sc.get("end_ns", float("inf"))
                    if when_ns and when_ns <= ts <= end_ns:
                        phase = "when"
                        break
            phased.append((f, t, label, ts, phase, tid, is_async))
        edges = phased

    # Collect participant names in canonical order
    _CANONICAL_ORDER = ["Host", "Participant", "Railway", "Daemon", "Addons"]
    all_actors = set()
    for e in edges:
        all_actors.add(e[0])
        all_actors.add(e[1])
    participants = [p for p in _CANONICAL_ORDER if p in all_actors]
    for e in edges:
        for p in (e[0], e[1]):
            if p not in participants:
                participants.append(p)

    def _render_edge(e: tuple) -> str:
        f, t, label, _ts, phase, tid, is_async = e
        arrow = "-->" if is_async else "->"
        color = "[#gray]" if phase == "given" else ""
        # Prefix with trace hash for correlation: [XX]
        trace_hash = f"[{hash(tid) % 100:02d}] " if tid else ""
        return f'"{f}" {color}{arrow} "{t}": {trace_hash}{label}'

    lines = ["@startuml"]
    lines.append("hide footbox")
    lines.append("")
    for p in participants:
        lines.append(f'participant "{p}"')
    lines.append("")

    if scenarios:
        for i, sc in enumerate(scenarios):
            sc_edges = [e for e in edges if e[3] <= sc["end_ns"]
                        and (i == 0 or e[3] > scenarios[i - 1]["end_ns"])]
            sc_edges = _deduplicate_edges(sc_edges)
            if not sc_edges:
                continue
            lines.append(f'== {sc["name"]} ==')
            for e in sc_edges:
                lines.append(_render_edge(e))
            lines.append("")
    else:
        for e in edges:
            lines.append(_render_edge(e))
    lines.append("")
    lines.append("@enduml")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: traces_to_puml.py <traces.jsonl> <family> <output.puml>")
        sys.exit(1)
    generate_puml(sys.argv[1], sys.argv[2], sys.argv[3])
