"""Make Quartz's graph look like Obsidian's graph view.

Quartz exposes forces and font size as options, but not node size, label
placement or colours, so this edits its renderer before the build. Every
replacement must match exactly once: if Quartz changes the code upstream,
the build fails here instead of silently shipping the old look.
"""
import pathlib
import sys

path = pathlib.Path(sys.argv[1])

PATCHES = [
    # Obsidian keeps hubs only a bit larger than leaves; sqrt made index/log/overview giant.
    ("return 2 + Math.sqrt(numLinks)",
     "return 3 + Math.log2(1 + numLinks)"),
    # One neutral node colour like Obsidian, no teal "visited" nodes; current page keeps the accent.
    ("""    } else if (visited.has(d.id) || d.id.startsWith("tags/")) {
      return computedStyleMap["--tertiary"]
    } else {
      return computedStyleMap["--gray"]
    }""",
     """    } else {
      return computedStyleMap["--darkgray"]
    }"""),
    # Labels visible from the start and hanging under the node, not floating above it.
    ("""      alpha: 0,
      anchor: { x: 0.5, y: 1.2 },""",
     """      alpha: 1,
      anchor: { x: 0.5, y: 0 },"""),
    ("""      color: color(n),
      alpha: 1,
      active: false,
    }

    nodeRenderData.push(nodeRenderDatum)""",
     """      color: color(n),
      alpha: 1,
      active: false,
      radius: nodeRadius(n),
    }

    nodeRenderData.push(nodeRenderDatum)"""),
    ("n.label.position.set(x + width / 2, y + height / 2)",
     "n.label.position.set(x + width / 2, y + height / 2 + n.radius + 2)"),
    # Keep a margin around each node for its label, so neighbouring labels don't collide.
    ("forceCollide<NodeData>((n) => nodeRadius(n))",
     "forceCollide<NodeData>((n) => nodeRadius(n) + 14)"),
    # Hairline edges that stay the same thickness on screen at any zoom, like Obsidian:
    # the stage scales by the zoom factor k, so divide the width by k.
    (".stroke({ alpha: l.alpha, width: 1, color: l.color })",
     ".stroke({ alpha: l.alpha * (l.active ? 1 : 0.6), width: 0.6 / currentTransform.k, color: l.color })"),
    # Hover like Obsidian: the node and its links turn purple, everything else dims.
    ('l.color = l.active ? computedStyleMap["--gray"] : computedStyleMap["--lightgray"]',
     'l.color = l.active ? "#8b5cf6" : computedStyleMap["--lightgray"]'),
    ("""      tweenGroup.add(new Tweened<Graphics>(n.gfx, tweenGroup).to({ alpha }, 200))""",
     """      n.gfx.tint = hoveredNodeId === n.simulationData.id ? "#8b5cf6" : 0xffffff
      tweenGroup.add(new Tweened<Graphics>(n.gfx, tweenGroup).to({ alpha }, 200))"""),
    # Labels stay fully visible at normal zoom and fade out only when zoomed far out.
    ("let scaleOpacity = Math.max((scale - 1) / 3.75, 0)",
     "let scaleOpacity = Math.min(Math.max((scale - 0.5) / 0.5, 0), 1)"),
    # Node preview (graph-preview.ts). Every hover change, in or out, goes through
    # updateHoverInfo: that is where the hint chip learns which note is under the mouse.
    ('import { D3Config } from "../Graph"',
     'import { D3Config } from "../Graph"\nimport { graphPreviewHover, graphPreviewOpen } from "./graph-preview"'),
    ("    hoveredNodeId = newHoveredId\n",
     "    hoveredNodeId = newHoveredId\n"
     "    graphPreviewHover(newHoveredId === null ? null\n"
     "      : new URL(resolveRelative(fullSlug, newHoveredId as SimpleSlug), window.location.toString()))\n"),
    # A click opens the note in a modal over the graph; ⌘/Ctrl-click navigates as before.
    # d3-drag ignores Ctrl-clicks by default, which would make Ctrl-click do nothing.
    ("""        .container(() => app.canvas)
""",
     """        .container(() => app.canvas)
        .filter((event) => !event.button)
"""),
    ("""            const targ = resolveRelative(fullSlug, node.id)
            window.spaNavigate(new URL(targ, window.location.toString()))""",
     """            const url = new URL(resolveRelative(fullSlug, node.id), window.location.toString())
            const click = event.sourceEvent as MouseEvent | undefined
            click?.metaKey || click?.ctrlKey ? window.spaNavigate(url) : graphPreviewOpen(url)"""),
    ("""      node.gfx.on("click", () => {
        const targ = resolveRelative(fullSlug, node.simulationData.id)
        window.spaNavigate(new URL(targ, window.location.toString()))""",
     """      node.gfx.on("click", (click) => {
        const targ = resolveRelative(fullSlug, node.simulationData.id)
        const url = new URL(targ, window.location.toString())
        click.metaKey || click.ctrlKey ? window.spaNavigate(url) : graphPreviewOpen(url)"""),
]

# The "Graph View" heading itself opens the full graph, with the graph icon right
# after the text: the icon alone, in the corner of the small graph, was barely visible.
# The button keeps its global-graph-icon class, which is what graph.inline.ts binds to.
GRAPH_TSX_PATCHES = [
    ("""        <h3>{i18n(cfg.locale).components.graph.title}</h3>
        <div class="graph-outer">
          <div class="graph-container" data-cfg={JSON.stringify(localGraph)}></div>
          <button class="global-graph-icon" aria-label="Global Graph">""",
     """        <h3>
          <button class="global-graph-icon graph-title" aria-label="Open the full graph">
            {i18n(cfg.locale).components.graph.title}"""),
    ("""          </button>
        </div>
        <div class="global-graph-outer">""",
     """          </button>
        </h3>
        <div class="graph-outer">
          <div class="graph-container" data-cfg={JSON.stringify(localGraph)}></div>
        </div>
        <div class="global-graph-outer">"""),
]


def apply(target: pathlib.Path, patches: list[tuple[str, str]]) -> None:
    # Keep Quartz's original next to it, so re-running (after a patch change) starts clean.
    original = target.with_name(target.name + ".orig")
    if not original.exists():
        original.write_text(target.read_text())
    src = original.read_text()
    for old, new in patches:
        count = src.count(old)
        if count != 1:
            sys.exit(f"patch-graph: expected 1 match in {target.name}, found {count}:\n{old}")
        src = src.replace(old, new)
    target.write_text(src)
    print(f"patch-graph: applied {len(patches)} patches to {target}")


apply(path, PATCHES)
apply(path.parents[1] / "Graph.tsx", GRAPH_TSX_PATCHES)
