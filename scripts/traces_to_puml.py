"""Generate PlantUML sequence diagrams from OTel trace JSONL files.

Generic transformation rules:
1. Collapse proxy chains (A -> Railway -> Daemon becomes A -> Daemon)
2. Collapse broadcast relay (Daemon -> Railway -> Browser becomes Daemon -> Browser)
3. Participant names from service.name attribute
4. Arrow labels from span names
5. Same-service parent->child spans are filtered out (auto-instrumented urllib
   / ASGI client spans add no information). Exception: spans whose name starts
   with "step:" pass through and render as self-messages, used to highlight an
   important sub-step inside a request (e.g. step:download_via_railway).
6. Infer host origin from /host/ path patterns in root daemon spans
7. Infer broadcast/notify targets from span name prefixes
8. Railway root spans (browser parent missing) => Participant -> Railway
9. Activations: each non-async edge activates the destination for its span lifespan
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


def _extract_edges(spans: list[dict]) -> list[tuple[str, str, str, int, int, str, str, bool]]:
    """Extract edges from spans.

    Returns (from_svc, to_svc, label, start_time, end_time, bdd_phase, trace_id, is_async).
    is_async=True for broadcast/notify_host (rendered as dashed arrows).
    end_time drives PlantUML activate/deactivate brackets.
    """
    # Noise: spans that add no useful info to sequence diagrams
    _SKIP_PATTERNS = {"/api/status", "/static", "/favicon"}

    index = _build_span_index(spans)
    # Railway spans whose children include a different service are proxy parents
    _railway_proxy_parents = set()
    for s in spans:
        p = _parent_id(s)
        if p and p in index and _service_name(index[p]) == "Railway" and _service_name(s) != "Railway":
            _railway_proxy_parents.add(p)

    edges = []
    for span in spans:
        name = span.get("name", "")
        if any(p in name for p in _SKIP_PATTERNS):
            continue
        svc = _service_name(span)
        start = span.get("start_time", 0)
        end = span.get("end_time", start)
        pid = _parent_id(span)
        phase = span.get("attributes", {}).get("bdd.phase", "")
        tid = span.get("context", {}).get("trace_id", "")

        # Rule 7: broadcast:* and notify_host:* root spans from Daemon
        if svc == "Daemon" and name.startswith("broadcast:"):
            msg_type = name.split(":", 1)[1]
            edges.append(("Daemon", "Participant", msg_type, start, end, phase, tid, True))
            continue
        if svc == "Daemon" and name.startswith("notify_host:"):
            msg_type = name.split(":", 1)[1]
            edges.append(("Daemon", "Host", msg_type, start, end, phase, tid, True))
            continue

        # Rule 6: Daemon root HTTP spans
        # - X-Actor header (captured as "actor" attr) wins, e.g. FileSystem.
        # - Otherwise, /host/ path patterns attribute to "Host".
        if svc == "Daemon" and (not pid or pid not in index):
            actor_attr = (span.get("attributes", {}).get("actor") or "").strip()
            if actor_attr:
                edges.append((actor_attr, "Daemon", name, start, end, phase, tid, False))
                continue
            if _HOST_PATH_RE.match(name):
                edges.append(("Host", "Daemon", name, start, end, phase, tid, False))
                continue

        # Rule 8: Railway root HTTP spans (browser parent not in traces) => <actor> -> Railway.
        # If the request carried an X-Actor header (captured as the "actor" span
        # attribute, e.g. "FileSystem" for daemon-watcher-triggered invalidates),
        # use it as the source. Without an explicit actor we fall back to the
        # generic "Participant" placeholder and skip proxy parents (those have
        # non-Railway children and are handled by _collapse_proxy). When actor
        # IS set we emit the edge regardless of proxy-parent status, since the
        # endpoint really did originate from that actor and the user wants to
        # see the trigger arrow even if Railway also calls back into the daemon.
        if svc == "Railway" and (not pid or pid not in index):
            sid = _span_id(span)
            actor_attr = (span.get("attributes", {}).get("actor") or "").strip()
            if (re.match(r"(GET|POST|PUT|DELETE|PATCH|HEAD) /\S", name)
                    and "/ws/" not in name
                    and (actor_attr or sid not in _railway_proxy_parents)):
                actor = actor_attr or "Participant"
                edges.append((actor, "Railway", name, start, end, phase, tid, False))
                continue

        # Standard parent->child edge.
        if not pid or pid not in index:
            continue
        parent = index[pid]
        from_svc = _service_name(parent)
        to_svc = _service_name(span)
        # Rule 5: skip same-service edges (auto-instrumented urllib / ASGI noise),
        # EXCEPT explicit "step:" spans which highlight an important sub-step.
        if from_svc == to_svc and not name.startswith("step:"):
            continue
        label = name or "unknown"
        edges.append((from_svc, to_svc, label, start, end, phase, tid, False))
    return edges


def _collapse_proxy(edges: list[tuple]) -> list[tuple]:
    """Rule 1: Railway->Daemon edges become Participant->Daemon (Railway is a proxy).

    The collapsed edge inherits the daemon span's start_time/end_time so the
    activation bar reflects the daemon's actual work duration.
    """
    result = []
    skip = set()
    for i, e in enumerate(edges):
        f, t, label, ts, end, phase, tid, is_async = e
        if i in skip:
            continue
        if t == "Railway" and label == "proxy_request":
            for j in range(i + 1, len(edges)):
                e2 = edges[j]
                if e2[0] == "Railway" and e2[1] == "Daemon":
                    source = "Participant" if f == "Railway" else f
                    result.append((source, "Daemon", e2[2], e2[3], e2[4], phase, tid, is_async))
                    skip.add(j)
                    break
            else:
                result.append(e)
        elif f == "Railway" and t == "Daemon":
            result.append(("Participant", "Daemon", label, ts, end, phase, tid, is_async))
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
                    # Preserve the original Daemon span timing (e[3], e[4]).
                    result.append(("Daemon", e2[1], label, e[3], e[4], e[5], e[6], e[7]))
                    skip.add(j)
                    break
            else:
                result.append(e)
        else:
            result.append(e)
    return result


def _deduplicate_edges(edges: list[tuple]) -> list[tuple]:
    """No-op: kept for API compatibility but dedup is disabled.

    Every trace edge is preserved to show the full flow (e.g., two
    participants both registering appear as two separate arrows).
    """
    return edges


def generate_puml(traces_path: str, family: str, output: str,
                  scenarios: list[dict] | None = None,
                  title: str | None = None,
                  participant_names: dict[str, str] | None = None) -> None:
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

    # Resolve "Participant" to named actors (e.g., "Alice", "Bob") using
    # participant.id span attribute matched against the participant_names map.
    if participant_names:
        # Build trace_id → participant name from spans with participant.id attribute
        trace_to_name: dict[str, str] = {}
        for span in spans:
            pid = span.get("attributes", {}).get("participant.id", "")
            if pid and pid in participant_names:
                tid = span.get("context", {}).get("trace_id", "")
                if tid:
                    trace_to_name[tid] = participant_names[pid]
        # Replace "Participant" with named actor from trace_id mapping.
        # For unresolved edges (no trace match), keep "Participant" for broadcasts
        # (they target all participants) but try to assign to a known participant
        # for request edges (from="Participant").
        all_names = sorted(set(participant_names.values()))
        default_actor = f"Participant\\n{all_names[0]}" if len(all_names) == 1 else "Participant"
        named_actors = [f"Participant\\n{n}" for n in all_names]
        named = []
        for f, t, label, ts, end, phase, tid, is_async in edges:
            resolved = trace_to_name.get(tid)
            if resolved:
                actor = f"Participant\\n{resolved}"
                if f == "Participant":
                    f = actor
                if t == "Participant":
                    t = actor
                named.append((f, t, label, ts, end, phase, tid, is_async))
            elif is_async and t == "Participant" and named_actors:
                # Unresolved broadcast — fan out to every known named participant
                # (the broadcast really did go to all of them; we just couldn't
                # attribute the trace to a single one).
                for actor in named_actors:
                    named.append((f, actor, label, ts, end, phase, tid, is_async))
            elif f == "Participant" and not is_async:
                # Unresolved request from participant — use default
                named.append((default_actor, t, label, ts, end, phase, tid, is_async))
            else:
                named.append((f, t, label, ts, end, phase, tid, is_async))
        edges = named
        # Drop any remaining edges referencing the generic "Participant"
        # placeholder (e.g. broadcasts emitted before any named participant
        # joined, or unresolvable proxy calls).
        edges = [e for e in edges if e[0] != "Participant" and e[1] != "Participant"]

    if not scenarios:
        edges = _deduplicate_edges(edges)

    # Assign phases from scenario timestamp boundaries
    if scenarios:
        phased = []
        for e in edges:
            f, t, label, ts, end, phase, tid, is_async = e
            if not phase:
                phase = ""
                for sc in scenarios:
                    start_ns = sc.get("start_ns", 0)
                    when_ns = sc.get("when_start_ns", 0)
                    end_ns = sc.get("end_ns", float("inf"))
                    if start_ns <= ts <= end_ns:
                        phase = "when" if when_ns and ts >= when_ns else "given"
                        break
                if not phase:
                    phase = "given"  # unmatched = setup noise
            phased.append((f, t, label, ts, end, phase, tid, is_async))
        edges = phased

    # Collect actor names in canonical order
    all_actors = set()
    for e in edges:
        all_actors.add(e[0])
        all_actors.add(e[1])
    # Named participants ("Participant\\nAlice") use the literal two-character
    # sequence backslash+n as PlantUML's line-break marker — match that prefix.
    named_pax = sorted(a for a in all_actors if a.startswith("Participant\\n"))
    _CANONICAL_ORDER = (
        ["Host"]
        + (named_pax or (["Participant"] if "Participant" in all_actors else []))
        + ["Daemon", "FileSystem", "Railway", "GDrive", "Addons"]
    )
    participants = [p for p in _CANONICAL_ORDER if p in all_actors]
    for e in edges:
        for p in (e[0], e[1]):
            if p not in participants:
                participants.append(p)

    # 10 visually distinct trace colors, cycled by trace order. Ordered so each
    # neighbour (and the wrap-around) sits in a far-apart hue/lightness slot —
    # avoids the "two greens in a row" effect from the previous palette which
    # had multiple near-duplicate shades (red/dark-red, blue/dark-blue, etc).
    _TRACE_COLORS = [
        "#1F77B4",  # blue
        "#D62728",  # red
        "#2CA02C",  # green
        "#FF7F0E",  # orange
        "#9467BD",  # purple
        "#17BECF",  # cyan
        "#BCBD22",  # olive
        "#E377C2",  # pink
        "#8C564B",  # brown
        "#7F7F7F",  # gray
    ]

    # Assign a sequential 1-based digit label to each trace_id in order of
    # first appearance. Easier to follow than hash digits.
    trace_tags: dict[str, tuple[str, str]] = {}  # tid → (label, color)
    for e in edges:
        tid = e[6]
        if tid and tid not in trace_tags:
            idx = len(trace_tags) + 1  # 1-based
            color = _TRACE_COLORS[(idx - 1) % len(_TRACE_COLORS)]
            trace_tags[tid] = (str(idx), color)

    def _render_edge(e: tuple) -> str:
        f, t, label, _ts, _end, phase, tid, is_async = e
        arrow = "-->" if is_async else "->"
        color = "[#gray]" if phase == "given" else ""
        tag = trace_tags.get(tid)
        if tag:
            tag_label, tag_color = tag
            trace_tag = f" <color:{tag_color}>[{tag_label}]</color>"
        else:
            trace_tag = ""
        return f'"{f}" {color}{arrow} "{t}": {label}{trace_tag}'

    def _interleave_activations(edge_list: list[tuple], indent: str = "") -> list[str]:
        """Render edges with activate/deactivate brackets per Rule 9.

        A non-async edge activates its destination only if at least one
        later edge originates from that destination during the span's
        lifespan — i.e. only spans that produce follow-up arrows in the
        diagram get an activation bar. Leaf calls (no observable
        sub-activity) stay unbracketed to keep the diagram clean.
        Activations close in end_time order; OTel parent-child nesting
        guarantees this matches PlantUML's per-actor LIFO stack semantics.
        """
        # Pre-compute whether each edge's destination has a follow-up
        # outgoing arrow during this edge's [start, end] window.
        has_child = [False] * len(edge_list)
        for i, edge_i in enumerate(edge_list):
            _, t_i, _, start_i, end_i, _, _, _ = edge_i
            for j in range(i + 1, len(edge_list)):
                f_j, _, _, start_j, _, _, _, _ = edge_list[j]
                if start_j > end_i:
                    break
                if f_j == t_i and start_j >= start_i:
                    has_child[i] = True
                    break

        out: list[str] = []
        active: list[tuple[int, str]] = []  # (end_time, service), end-time ascending
        for i, edge in enumerate(edge_list):
            _f, t, _label, start, end, _phase, _tid, is_async = edge
            while active and active[0][0] <= start:
                _, svc = active.pop(0)
                out.append(f'{indent}deactivate "{svc}"')
            out.append(f"{indent}{_render_edge(edge)}")
            if not is_async and has_child[i]:
                out.append(f'{indent}activate "{t}"')
                pos = 0
                while pos < len(active) and active[pos][0] <= end:
                    pos += 1
                active.insert(pos, (end, t))
        while active:
            _, svc = active.pop(0)
            out.append(f'{indent}deactivate "{svc}"')
        return out

    lines = ["@startuml"]
    lines.append("hide footbox")
    if title:
        from datetime import datetime
        lines.append(f"title {title}")
        local_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines.append(f"caption <color:gray>Generated {local_time}</color>")
    lines.append("")
    for p in participants:
        lines.append(f'participant "{p}"')
    lines.append("")

    if scenarios:
        for sc in scenarios:
            start = sc.get("start_ns", 0)
            end = sc["end_ns"]
            sc_edges = [e for e in edges if start <= e[3] <= end]
            sc_edges = _deduplicate_edges(sc_edges)
            if not sc_edges:
                continue
            lines.append(f'== {sc["name"]} ==')
            # Group Given-phase edges into a collapsed "init" block
            given_edges = [e for e in sc_edges if e[5] == "given"]
            when_edges = [e for e in sc_edges if e[5] != "given"]
            if given_edges and when_edges:
                lines.append("group init")
                lines.extend(_interleave_activations(given_edges, indent="  "))
                lines.append("end")
                lines.extend(_interleave_activations(when_edges))
            else:
                lines.extend(_interleave_activations(sc_edges))
            lines.append("")
    else:
        lines.extend(_interleave_activations(edges))
    lines.append("")
    lines.append("@enduml")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: traces_to_puml.py <traces.jsonl> <family> <output.puml>")
        sys.exit(1)
    generate_puml(sys.argv[1], sys.argv[2], sys.argv[3])
