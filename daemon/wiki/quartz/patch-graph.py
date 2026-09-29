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
    # Multi-day vaults (builder.mark_note_days): the latest day's notes are the
    # high-contrast grey, every earlier day's the dim one, so what the room added
    # today stands out. Same grey family on purpose: a hue per day read as noise.
    ("""    } else if (visited.has(d.id) || d.id.startsWith("tags/")) {
      return computedStyleMap["--tertiary"]
    } else {
      return computedStyleMap["--gray"]
    }
  }""",
     """    } else if (d.day) {
      return d.day === latestDay ? computedStyleMap["--graph-today"] : computedStyleMap["--graph-earlier"]
    } else {
      return computedStyleMap["--darkgray"]
    }
  }

  // Which grey is today, in the corner of the full graph.
  const days = new Map<number, string>()
  for (const n of graphData.nodes) if (n.day) days.set(n.day, n.dayLabel ?? String(n.day))
  const latestDay = Math.max(0, ...days.keys())
  if (days.size > 1 && graph.classList.contains("global-graph-container")) {
    const legend = document.createElement("div")
    legend.className = "graph-day-legend"
    const earlier = [...days].filter(([day]) => day !== latestDay).sort((a, b) => a[0] - b[0])
    for (const [label, cssVar] of [
      [days.get(latestDay)!, "--graph-today"],
      [earlier.map(([, l]) => l).join(" · "), "--graph-earlier"],
    ] as const) {
      const dot = document.createElement("i")
      dot.style.background = computedStyleMap[cssVar]
      const item = document.createElement("span")
      item.append(dot, label)
      legend.append(item)
    }
    graph.append(legend)
  }"""),
    ("""type NodeData = {
  id: SimpleSlug
  text: string
  tags: string[]
} & SimulationNodeDatum""",
     """type NodeData = {
  id: SimpleSlug
  text: string
  tags: string[]
  day?: number
  dayLabel?: string
} & SimulationNodeDatum"""),
    ("""      tags: data.get(url)?.tags ?? [],
    }""",
     """      tags: data.get(url)?.tags ?? [],
      day: data.get(url)?.day,
      dayLabel: data.get(url)?.dayLabel,
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
    ("""    "--darkgray",
    "--bodyFont",
  ] as const""",
     """    "--darkgray",
    "--bodyFont",
    "--graph-today",
    "--graph-earlier",
  ] as const"""),
    # Hairline edges that stay the same thickness on screen at any zoom, like Obsidian:
    # the stage scales by the zoom factor k, so divide the width by k. A lit edge
    # (hovered dot, or a link hovered in the note pane) is thicker, to stand out.
    (".stroke({ alpha: l.alpha, width: 1, color: l.color })",
     ".stroke({ alpha: l.alpha * (l.active ? 1 : 0.6), width: (l.active ? 1.6 : 0.6) / currentTransform.k, color: l.color })"),
    # Hover like Obsidian: the node and its links turn purple, everything else dims.
    ('l.color = l.active ? computedStyleMap["--gray"] : computedStyleMap["--lightgray"]',
     'l.color = l.active ? "#8b5cf6" : computedStyleMap["--lightgray"]'),
    ("""      tweenGroup.add(new Tweened<Graphics>(n.gfx, tweenGroup).to({ alpha }, 200))""",
     """      // Repainted, not tinted: a tint multiplies, so on light theme's dark-grey dots
      // "purple" came out almost black.
      const purple = hoveredNodeId === n.simulationData.id || selectedNodeId === n.simulationData.id
      n.gfx.clear().circle(0, 0, n.radius).fill({ color: purple ? "#8b5cf6" : n.color })
      tweenGroup.add(new Tweened<Graphics>(n.gfx, tweenGroup).to({ alpha }, 200))"""),
    # Labels stay fully visible at normal zoom and fade out only when zoomed far out.
    ("let scaleOpacity = Math.max((scale - 1) / 3.75, 0)",
     "let scaleOpacity = Math.min(Math.max((scale - 0.5) / 0.5, 0), 1)"),
    # Note pane (note-pane.ts): the full graph is the wiki's main screen, with the
    # selected note in a pane beside it. The selected dot stays purple (selectedNodeId)
    # until another one is picked; hovering a dot fetches its note ahead of the click.
    ("  let hoveredNodeId: string | null = null\n",
     "  let hoveredNodeId: string | null = null\n"
     "  let selectedNodeId: string | null = null\n"),
    ('import { D3Config } from "../Graph"',
     'import { D3Config } from "../Graph"\n'
     'import { PaneGraph, connectGraph, disconnectGraph, selectNote, warmNote } from "./note-pane"'),
    ("    hoveredNodeId = newHoveredId\n",
     "    hoveredNodeId = newHoveredId\n"
     "    if (newHoveredId !== null) warmNote(newHoveredId as SimpleSlug)\n"),
    # A click selects the note into the pane; the graph stays where it is.
    ("""            const targ = resolveRelative(fullSlug, node.id)
            window.spaNavigate(new URL(targ, window.location.toString()))""",
     """            void selectNote(node.id)"""),
    ("""      node.gfx.on("click", () => {
        const targ = resolveRelative(fullSlug, node.simulationData.id)
        window.spaNavigate(new URL(targ, window.location.toString()))""",
     """      node.gfx.on("click", () => {
        void selectNote(node.simulationData.id)"""),
    # The full graph answers the pane: which dot is selected, and which one a link in
    # the note points at. That one lights up with the selected dot and the edge
    # between them; the rest dims, as when hovering a dot.
    ("""  let stopAnimation = false
""",
     """  const isGlobal = graph.classList.contains("global-graph-container")
  const paneGraph: PaneGraph = {
    select(id) {
      selectedNodeId = id
      if (!dragging) renderPixiFromD3()
    },
    highlight(id) {
      hoveredNodeId = id
      const pair = new Set([id, selectedNodeId])
      for (const l of linkRenderData) {
        const { source, target } = l.simulationData
        l.active = id !== null && pair.has(source.id) && pair.has(target.id)
      }
      for (const n of nodeRenderData) n.active = id !== null && pair.has(n.simulationData.id)
      if (!dragging) renderPixiFromD3()
    },
  }
  if (isGlobal) connectGraph(paneGraph)

  let stopAnimation = false
"""),
    ("""  return () => {
    stopAnimation = true
    app.destroy()
  }""",
     """  return () => {
    stopAnimation = true
    if (isGlobal) disconnectGraph(paneGraph)
    app.destroy()
  }"""),
    # The full graph is always open: rendered on every page load, re-rendered to fit a
    # resized window, and neither Esc, a click outside it nor Ctrl+G closes it.
    ("      registerEscapeHandler(container, hideGlobalGraph)\n", ""),
    ("anyGlobalGraphOpen ? hideGlobalGraph() : renderGlobalGraph()",
     "if (!anyGlobalGraphOpen) void renderGlobalGraph()"),
    ("""  document.addEventListener("keydown", shortcutHandler)
""",
     """  document.addEventListener("keydown", shortcutHandler)
  void renderGlobalGraph()
  let resizeTimer = 0
  const refit = () => {
    clearTimeout(resizeTimer)
    resizeTimer = window.setTimeout(() => {
      cleanupGlobalGraphs()
      void renderGlobalGraph()
    }, 250)
  }
  window.addEventListener("resize", refit)
  window.addCleanup(() => window.removeEventListener("resize", refit))
"""),
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


# The day a note was born (wikiDay/wikiDayLabel frontmatter, stamped by
# builder.mark_note_days) travels to the graph in the content index.
CONTENT_INDEX_PATCHES = [
    ("""  date?: Date
  description?: string
}""",
     """  date?: Date
  description?: string
  day?: number
  dayLabel?: string
}"""),
    ("""            description: file.data.description ?? "",
          })""",
     """            description: file.data.description ?? "",
            day: file.data.frontmatter?.wikiDay as number | undefined,
            dayLabel: file.data.frontmatter?.wikiDayLabel as string | undefined,
          })"""),
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
apply(path.parents[2] / "plugins" / "emitters" / "contentIndex.tsx", CONTENT_INDEX_PATCHES)
