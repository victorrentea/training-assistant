#!/usr/bin/env python3
"""Generate C4 container diagrams from extracted PlantUML sequence files.

Reads docs/sequences/extracted/*.puml, infers containers and relationships
from the participant declarations and arrow lines, and writes C4 PlantUML
files to docs/sequences/gen/.

Usage:
    python3 scripts/sequence_to_c4.py                 # all extracted files
    python3 scripts/sequence_to_c4.py 06-slides.puml  # specific file(s)
    python3 scripts/sequence_to_c4.py --render        # also render SVGs
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_DIR = ROOT / "docs" / "sequences" / "extracted"
GEN_DIR = ROOT / "docs" / "sequences" / "gen"

# ---------------------------------------------------------------------------
# Participant classification
# ---------------------------------------------------------------------------

@dataclass
class ParticipantDef:
    c4_type: str        # Person | Container | System_Ext
    label: str          # display name
    tech: str = ""      # technology string (for Container)
    desc: str = ""      # description

# Raw participant name (after normalisation) → C4 definition
_KNOWN: dict[str, ParticipantDef] = {
    "Host": ParticipantDef("Person", "Host", desc="Controls the session and slides"),
    "Participant": ParticipantDef("Person", "Participant", desc="Follows slides in browser"),
    "Railway": ParticipantDef(
        "Container", "Railway Backend", "FastAPI on Railway",
        "Transparent proxy for participant REST; triggers GDrive slide downloads.",
    ),
    "Daemon": ParticipantDef(
        "Container", "Training Daemon", "Python / FastAPI (localhost)",
        "Owns session state, slide orchestration, and feature state machines.",
    ),
    "GDrive": ParticipantDef("System_Ext", "Google Drive", desc="Source of slide PDF exports"),
    "Claude": ParticipantDef("System_Ext", "Anthropic Claude API", desc="LLM used by the daemon"),
    "macOS Addons": ParticipantDef("System_Ext", "victor-macos-addons", desc="Local slide/overlay event bridge"),
}

# Identifiers used in C4 (no spaces/special chars)
def _c4_id(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", raw).strip("_").lower()


def _classify(raw: str) -> ParticipantDef:
    if raw in _KNOWN:
        return _KNOWN[raw]
    return ParticipantDef("System_Ext", raw, desc="")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_COLOR_TAG_RE = re.compile(r"<color[^>]*>[^<]*</color>")
_PARTICIPANT_RE = re.compile(r'^participant\s+"([^"]+)"')
_ARROW_RE = re.compile(
    r'^"([^"]+)"\s+\[?(?:#[0-9a-fA-F]+)?\]?(-+>|--+>)\s+"([^"]+)":\s*(.+)$'
)


def _normalise_name(raw: str) -> str:
    """Strip newline suffixes like 'Participant\\nAlice' → 'Participant'."""
    return raw.split("\\n")[0].strip()


def _clean_label(label: str) -> str:
    label = _COLOR_TAG_RE.sub("", label).strip()
    # strip trailing trace hash e.g. " [AB]"
    label = re.sub(r"\s+\[[0-9A-Fa-f]{2}\]\s*$", "", label).strip()
    return label


@dataclass
class Edge:
    src: str
    dst: str
    label: str
    is_async: bool  # --> dashed arrow


def parse_sequence(path: Path) -> tuple[list[str], list[Edge]]:
    """Return (participants, edges) from a sequence .puml file."""
    participants: list[str] = []
    seen_participants: set[str] = set()
    edges: list[Edge] = []

    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("'") or line.startswith("@") or not line:
            continue

        m = _PARTICIPANT_RE.match(line)
        if m:
            name = _normalise_name(m.group(1))
            if name not in seen_participants:
                seen_participants.add(name)
                participants.append(name)
            continue

        m = _ARROW_RE.match(line)
        if m:
            src = _normalise_name(m.group(1))
            arrow = m.group(2)
            dst = _normalise_name(m.group(3))
            label = _clean_label(m.group(4))
            is_async = "--" in arrow
            edges.append(Edge(src, dst, label, is_async))

    return participants, edges


# ---------------------------------------------------------------------------
# C4 generation
# ---------------------------------------------------------------------------

@dataclass
class RelKey:
    src: str
    dst: str
    is_async: bool

    def __hash__(self):
        return hash((self.src, self.dst, self.is_async))

    def __eq__(self, other):
        return (self.src, self.dst, self.is_async) == (other.src, other.dst, other.is_async)


def _build_c4(
    title: str,
    source_rel: str,
    participants: list[str],
    edges: list[Edge],
) -> str:
    # Deduplicate and group labels per (src, dst, sync/async)
    rel_labels: dict[RelKey, list[str]] = defaultdict(list)
    seen_labels: dict[RelKey, set[str]] = defaultdict(set)
    for e in edges:
        key = RelKey(e.src, e.dst, e.is_async)
        if e.label and e.label not in seen_labels[key]:
            seen_labels[key].add(e.label)
            rel_labels[key].append(e.label)

    defs = {p: _classify(p) for p in participants}

    # Separate internal containers from external/persons
    boundary_types = {"Container"}
    boundary_members = [p for p, d in defs.items() if d.c4_type in boundary_types]
    outer_members = [p for p in participants if p not in boundary_members]

    lines: list[str] = []
    lines.append("@startuml")
    c4_diagram_id = re.sub(r"[^a-zA-Z0-9]", "_", title)
    lines.append(f"!define DIAGRAM_ID {c4_diagram_id}")
    lines.append("!include <C4/C4_Container>")
    lines.append("")
    lines.append(f'title {title}')
    lines.append(f'caption <color:gray>Generated {date.today().isoformat()} from {source_rel}</color>')
    lines.append("LAYOUT_WITH_LEGEND()")
    lines.append("")

    for p in outer_members:
        d = defs[p]
        pid = _c4_id(p)
        if d.c4_type == "Person":
            lines.append(f'Person({pid}, "{d.label}", "{d.desc}")')
        else:
            lines.append(f'System_Ext({pid}, "{d.label}", "{d.desc}")')

    lines.append("")
    lines.append('System_Boundary(workshop, "Workshop Tool") {')
    for p in boundary_members:
        d = defs[p]
        pid = _c4_id(p)
        lines.append(f'    Container({pid}, "{d.label}", "{d.tech}", "{d.desc}")')
    lines.append("}")
    lines.append("")

    for key, labels in rel_labels.items():
        src_id = _c4_id(key.src)
        dst_id = _c4_id(key.dst)
        # Limit label length for readability
        combined = ", ".join(labels[:3])
        if len(labels) > 3:
            combined += f", +{len(labels) - 3} more"
        tech = "WS push" if key.is_async else "REST"
        lines.append(f'Rel({src_id}, {dst_id}, "{combined}", "{tech}")')

    lines.append("")
    lines.append("@enduml")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _process_file(src: Path, render: bool) -> Path:
    title_raw = src.stem  # e.g. "06-slides"
    title = re.sub(r"^\d+-", "", title_raw).replace("-", " ").title()
    title = f"{title} — C4 Container View"

    participants, edges = parse_sequence(src)

    source_rel = str(src.relative_to(ROOT))
    c4_puml = _build_c4(title, source_rel, participants, edges)

    GEN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GEN_DIR / f"{src.stem}-c4.puml"
    out_path.write_text(c4_puml)
    print(f"generated {out_path.relative_to(ROOT)}")

    if render:
        from render_puml_svgs import render_puml_files
        render_puml_files([out_path])
        svg = GEN_DIR / "svg" / f"{out_path.stem}.svg"
        print(f"rendered  {svg.relative_to(ROOT)}")

    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Specific .puml filenames (basename only)")
    parser.add_argument("--render", action="store_true", help="Also render SVGs via plantuml")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.files:
        sources = [EXTRACTED_DIR / f for f in args.files]
    else:
        sources = sorted(EXTRACTED_DIR.glob("*.puml"))

    if not sources:
        print("No extracted sequence files found.", file=sys.stderr)
        return 1

    for src in sources:
        if not src.exists():
            print(f"Not found: {src}", file=sys.stderr)
            return 1
        _process_file(src, args.render)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
