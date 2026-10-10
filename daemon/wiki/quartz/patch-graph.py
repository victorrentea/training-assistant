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
    # One neutral node colour like Obsidian; the current page keeps the accent.
    # Seen/unseen instead of Quartz's teal "visited": a note never opened
    # on this browser is the high-contrast grey, one already read the dim one
    # (note-pane.ts keeps the list), so what is left to read stands out.
    ("""    } else if (visited.has(d.id) || d.id.startsWith("tags/")) {
      return computedStyleMap["--tertiary"]
    } else {
      return computedStyleMap["--gray"]
    }""",
     """    } else {
      return isSeen(d.id) ? computedStyleMap["--wiki-seen"] : computedStyleMap["--wiki-unseen"]
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
      badge,
      glow,
    }

    nodeRenderData.push(nodeRenderDatum)"""),
    ("n.label.position.set(x + width / 2, y + height / 2)",
     "n.label.position.set(x + width / 2, y + height / 2 + n.radius + 2)"),
    # Badges on the dots (graph-badges.ts): a picture, and the count of external links,
    # so the notes worth opening stand out. In a container of their own, above the dots:
    # the zoom handler fades every label when zoomed out, and the badges must stay.
    ("""  stage.addChild(nodesContainer, labelsContainer, linkContainer)
""",
     """  stage.addChild(nodesContainer, labelsContainer, linkContainer)
  const badgesContainer = new Container<NoteBadge>({ zIndex: 4, isRenderGroup: true, eventMode: "none" })
  stage.addChild(badgesContainer)
  const noteBadges = await loadBadges(fullSlug)
  const badgeColors: BadgeColors = {
    img: computedStyleMap["--wiki-badge-img"],
    link: computedStyleMap["--wiki-badge-link"],
    halo: computedStyleMap["--light"],
    font: computedStyleMap["--bodyFont"],
  }
  // The glow (graph-glow.ts): under the edges and the dots, as strong as the note's
  // topic is common in the trainer's past sessions.
  const glowContainer = new Container({ zIndex: 0, isRenderGroup: true, eventMode: "none" })
  stage.addChild(glowContainer)
  const noteGlow = await loadGlow(fullSlug)
  const glowColor = computedStyleMap["--wiki-glow"]
"""),
    ("""    labelsContainer.addChild(label)
""",
     """    labelsContainer.addChild(label)
    const badge = makeBadge(noteBadges.get(nodeId), badgeColors)
    if (badge) badgesContainer.addChild(badge)
    const glow = makeGlow(noteGlow.get(nodeId), nodeRadius(n), glowColor)
    if (glow) glowContainer.addChild(glow)
"""),
    ("""        n.label.position.set(x + width / 2, y + height / 2 + n.radius + 2)
      }
""",
     """        n.label.position.set(x + width / 2, y + height / 2 + n.radius + 2)
      }
      n.badge?.place(x + width / 2, y + height / 2, n.radius)
      n.glow?.position.set(x + width / 2, y + height / 2)
"""),
    # Keep a margin around each node for its label, so neighbouring labels don't collide.
    ("forceCollide<NodeData>((n) => nodeRadius(n))",
     "forceCollide<NodeData>((n) => nodeRadius(n) + 14)"),
    ("""    "--darkgray",
    "--bodyFont",
  ] as const""",
     """    "--darkgray",
    "--bodyFont",
    "--wiki-seen",
    "--wiki-unseen",
    "--wiki-badge-img",
    "--wiki-badge-link",
    "--wiki-glow",
  ] as const"""),
    # Hairline edges that stay the same thickness on screen at any zoom, like Obsidian:
    # the stage scales by the zoom factor k, so divide the width by k. A lit edge
    # (hovered dot, or a link hovered in the note popover) is thicker, to stand out.
    (".stroke({ alpha: l.alpha, width: 1, color: l.color })",
     ".stroke({ alpha: l.alpha * (l.active ? 1 : 0.6), width: (l.active ? 1.6 : 0.6) / currentTransform.k, color: l.color })"),
    # Hover: the node and its links turn purple; the rest keep their look, without the
    # dimming Quartz applies to edges even with focusOnHover off (nodes: quartz.layout.ts).
    ("alpha = l.active ? 1 : 0.2",
     "alpha = 1"),
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
    # Note popover (note-pane.ts): the full graph is the wiki's main screen. The dot
    # whose note is open stays purple (selectedNodeId) until the popover closes.
    ("  let hoveredNodeId: string | null = null\n",
     "  let hoveredNodeId: string | null = null\n"
     "  let selectedNodeId: string | null = null\n"),
    ('import { D3Config } from "../Graph"',
     'import { D3Config } from "../Graph"\n'
     'import { BadgeColors, NoteBadge, loadBadges, makeBadge } from "./graph-badges"\n'
     'import { loadGlow, makeGlow } from "./graph-glow"\n'
     'import { PaneGraph, connectGraph, disconnectGraph, graphSettled, hidePeek, isSeen, setShowHome, showHome, toggleNote, warmNote } from "./note-pane"'),
    # Hovering a dot fetches its note ahead of the click (note-pane.ts).
    ("    hoveredNodeId = newHoveredId\n",
     "    hoveredNodeId = newHoveredId\n"
     "    if (newHoveredId !== null) warmNote(newHoveredId as SimpleSlug)\n"),
    # A click opens the dot's note in the popover, or closes it on the open dot;
    # the graph stays where it is.
    ("""            const targ = resolveRelative(fullSlug, node.id)
            window.spaNavigate(new URL(targ, window.location.toString()))""",
     """            toggleNote(node.id)"""),
    ("""      node.gfx.on("click", () => {
        const targ = resolveRelative(fullSlug, node.simulationData.id)
        window.spaNavigate(new URL(targ, window.location.toString()))""",
     """      node.gfx.on("click", () => {
        toggleNote(node.simulationData.id)"""),
    # The full graph answers the popover: which dot is open, and which one a link in
    # the note points at. That one lights up with the selected dot and the edge
    # between them, as when hovering a dot. It also tells where a dot is on screen,
    # so a note the trainer opened (Follow) pops up by its dot, and when the layout
    # has come to rest.
    ("""  let stopAnimation = false
""",
     """  const isGlobal = graph.classList.contains("global-graph-container")
  const paneGraph: PaneGraph = {
    select(id) {
      selectedNodeId = id
      for (const n of nodeRenderData) n.color = color(n.simulationData)
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
    position(id) {
      const node = graphData.nodes.find((n) => n.id === id)
      if (node?.x === undefined || node.y === undefined) return null
      const rect = app.canvas.getBoundingClientRect()
      const x = rect.left + currentTransform.x + (node.x + width / 2) * currentTransform.k
      const y = rect.top + currentTransform.y + (node.y + height / 2) * currentTransform.k
      const inView = (v: number, lo: number, hi: number) => v >= lo && v <= hi
      if (!inView(x, Math.max(0, rect.left), Math.min(innerWidth, rect.right))) return null
      if (!inView(y, Math.max(0, rect.top), Math.min(innerHeight, rect.bottom))) return null
      return { x, y }
    },
  }
  if (isGlobal) {
    connectGraph(paneGraph)
    simulation.on("end.pane", () => graphSettled(paneGraph))
  }

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
  // Dragged dots and zoom back to the start: a fresh render lays the graph out the
  // same way every time (d3 seeds the positions deterministically).
  for (const container of containers) {
    if (container.querySelector(".graph-reset")) continue
    const reset = document.createElement("button")
    reset.className = "graph-reset"
    reset.textContent = "⟲ Reset layout"
    reset.addEventListener("click", () => {
      cleanupGlobalGraphs()
      void renderGlobalGraph()
    })
    // Next to it, the Home pill shows or hides the Home dot: it links to every note,
    // so it pulls the graph into a star and hides the clusters (Victor, 2026-10-09).
    const home = document.createElement("button")
    home.className = "graph-reset graph-home"
    home.textContent = "⌂ Home"
    home.classList.toggle("on", showHome())
    home.addEventListener("click", () => {
      setShowHome(!showHome())
      home.classList.toggle("on", showHome())
      cleanupGlobalGraphs()
      void renderGlobalGraph()
    })
    container.append(reset, home)
  }
"""),
    # Panning or scroll-zooming closes the open note: its dot moves away from the
    # popover (sourceEvent is null only for a zoom set from code).
    ("""        .on("zoom", ({ transform }) => {
          currentTransform = transform
""",
     """        .on("zoom", ({ transform, sourceEvent }) => {
          if (sourceEvent) hidePeek()
          currentTransform = transform
"""),
    # Without Home, which tied every note to the middle, the notes drift past the
    # window's edges: a light pull towards the centre keeps the whole graph in view.
    ("""    .force("collide", forceCollide<NodeData>((n) => nodeRadius(n) + 14).iterations(3))
""",
     """    .force("collide", forceCollide<NodeData>((n) => nodeRadius(n) + 14).iterations(3))
  if (graph.classList.contains("global-graph-container") && !showHome()) {
    simulation.force("x", forceX<NodeData>().strength(0.12)).force("y", forceY<NodeData>().strength(0.12))
  }
"""),
    ("""  forceRadial,
  zoomIdentity,""",
     """  forceRadial,
  forceX,
  forceY,
  zoomIdentity,"""),
    # Home off (the default): the full graph leaves out its dot and every edge to it.
    ("""  const links: SimpleLinkData[] = []
  const tags: SimpleSlug[] = []
""",
     """  if (graph.classList.contains("global-graph-container") && !showHome()) {
    data.delete("Home" as SimpleSlug)
  }
  const links: SimpleLinkData[] = []
  const tags: SimpleSlug[] = []
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
