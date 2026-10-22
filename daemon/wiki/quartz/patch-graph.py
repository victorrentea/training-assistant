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
    # A shining note (a takeaway, or starred by participants) is a yellow star: its
    # dot and its label turn the burst's gold, the label outlined in black so it stays
    # readable over the burst (Victor, 2026-10-21).
    ("""    } else if (visited.has(d.id) || d.id.startsWith("tags/")) {
      return computedStyleMap["--tertiary"]
    } else {
      return computedStyleMap["--gray"]
    }""",
     """    } else if (shineOf(d.id) > 0) {
      return computedStyleMap["--wiki-takeaway"]
    } else {
      return isSeen(d.id) ? computedStyleMap["--wiki-seen"] : computedStyleMap["--wiki-unseen"]
    }"""),
    ("""        fill: computedStyleMap["--dark"],
        fontFamily: computedStyleMap["--bodyFont"],""",
     """        fill: shineOf(nodeId) > 0 ? computedStyleMap["--wiki-takeaway"] : computedStyleMap["--dark"],
        stroke: shineOf(nodeId) > 0 ? SHINING_LABEL_STROKE : PLAIN_LABEL_STROKE,
        fontFamily: computedStyleMap["--bodyFont"],"""),
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
      takeaway,
    }

    nodeRenderData.push(nodeRenderDatum)"""),
    ("n.label.position.set(x + width / 2, y + height / 2)",
     "n.label.position.set(x + width / 2, y + height / 2 + n.radius + 2)"),
    # Badges on the dots (graph-badges.ts): a picture, and 🔗 ⚓ 🎬 once per link, anchor, short,
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
    count: computedStyleMap["--darkgray"],
    halo: computedStyleMap["--light"],
    font: computedStyleMap["--bodyFont"],
  }
  // The yellow ring around the note the trainer has open (Follow, note-pane.ts): above
  // the dots, under their labels; clicks go through it to the dot.
  const ring = new Graphics({ zIndex: 2.5, eventMode: "none" })
  stage.addChild(ring)
  const ringColor = computedStyleMap["--wiki-follow-ring"]
  let ringedNode: NodeRenderData | null = null
  // Key takeaways and participants' stars (graph-takeaway.ts): a golden starburst over
  // the edges, under the dots, and a star left of each dot, above everything - the
  // trainer's takeaway on his machine, the participant's own star in the participant
  // page.
  // From level 3 a soft glow spreads under the bursts, under every dot's burst.
  const takeawayHazeContainer = new Container({ zIndex: 1.4, isRenderGroup: true, eventMode: "none" })
  const takeawayGlowContainer = new Container({ zIndex: 1.5, isRenderGroup: true, eventMode: "none" })
  const starsContainer = new Container({ zIndex: 4.5, eventMode: "passive" })
  stage.addChild(takeawayHazeContainer, takeawayGlowContainer, starsContainer)
  const takeawayColors: TakeawayColors = {
    on: computedStyleMap["--wiki-takeaway"],
    off: computedStyleMap["--wiki-takeaway-off"],
    halo: computedStyleMap["--light"],
    font: computedStyleMap["--bodyFont"],
  }
  let starredIds: ReadonlySet<string> = new Set()
  // For a test (the canvas has no DOM): where the starred dots and the other ends of
  // their edges are on screen right now.
  ;(graph as HTMLElement & { takeawaysOnScreen?: () => unknown }).takeawaysOnScreen = () => {
    const rect = app.canvas.getBoundingClientRect()
    const { x, y, k } = currentTransform
    const at = (d: NodeData) => ({ x: rect.left + x + k * (d.x! + width / 2), y: rect.top + y + k * (d.y! + height / 2) })
    return nodeRenderData
      .filter((n) => starredIds.has(n.simulationData.id))
      .map(({ simulationData: d, radius }) => ({
        id: d.id,
        ...at(d),
        r: k * radius,
        edges: linkRenderData
          .map(({ simulationData: { source, target } }) => (source.id === d.id ? target : target.id === d.id ? source : null))
          .filter((o): o is NodeData => o !== null)
          .map((o) => ({ id: o.id, starred: starredIds.has(o.id), ...at(o) })),
      }))
  }
"""),
    # Drawn every frame: it moves with its dot, stays the same thickness on screen at
    # any zoom, like the edges, and breathes so a follower's eye finds it.
    ("""    tweens.forEach((t) => t.update(time))
""",
     """    ring.clear()
    const rn = ringedNode?.simulationData
    if (ringedNode && rn?.x !== undefined && rn.y !== undefined) {
      const k = currentTransform.k
      const pulse = (1 + Math.sin(time / 300)) / 2
      ring
        .circle(rn.x + width / 2, rn.y + height / 2, ringedNode.radius + (5 + 4 * pulse) / k)
        .stroke({ width: 3 / k, color: ringColor, alpha: 0.6 + 0.4 * pulse })
    }
    tweens.forEach((t) => t.update(time))
"""),
    ("""    labelsContainer.addChild(label)
""",
     """    labelsContainer.addChild(label)
    const badge = makeBadge(noteBadges.get(nodeId), badgeColors)
    if (badge) badgesContainer.addChild(badge)
    const takeaway = new TakeawayMark(nodeRadius(n), takeawayColors, starMode(), (on) =>
      starMode() === "voter" ? toggleStar(nodeId, on) : toggleTakeaway(nodeId, on))
    takeaway.set(dotShine(nodeId))
    takeawayHazeContainer.addChild(takeaway.glow)
    takeawayGlowContainer.addChild(takeaway.burst, takeaway.flare)
    starsContainer.addChild(takeaway.star)
"""),
    ("""        n.label.position.set(x + width / 2, y + height / 2 + n.radius + 2)
      }
""",
     """        n.label.position.set(x + width / 2, y + height / 2 + n.radius + 2)
      }
      n.badge?.place(x + width / 2, y + height / 2, n.radius)
      // The star right after the note's name, on its line (graph-takeaway.ts).
      // The star after the name, as one more word of it: a word space after its last
      // letter (the label's width takes in its outline, half of it each side), no
      // taller than a capital letter (Victor, 2026-10-23).
      const em = (n.label.style.fontSize as number) * n.label.scale.x
      const textEnd = n.label.width / 2 - (SHINING_LABEL_STROKE.width / 2) * n.label.scale.x
      n.takeaway?.place(x + width / 2, y + height / 2, textEnd + 0.25 * em, n.radius + 2 + n.label.height / 2, 0.68 * em, time)
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
    "--wiki-follow-ring",
    "--wiki-takeaway",
    "--wiki-takeaway-off",
  ] as const"""),
    # Hairline edges that stay the same thickness on screen at any zoom, like Obsidian:
    # the stage scales by the zoom factor k, so divide the width by k. A lit edge
    # (hovered dot, a link hovered in the note popover, or an edge of the dot whose
    # note is open) is thicker, to stand out.
    # The edges of the open dot also show their direction (Victor, 2026-10-16): an
    # arrowhead where the edge enters the dot its link points to. Quartz keeps A→B and
    # B→A as two edges on the same line, so a two-way link gets a head at each end.
    # A one-way edge of the open dot is drawn as dashes creeping slowly along it, from
    # the linking note to the linked one, on a faint line; a two-way edge stays solid
    # (Victor, 2026-10-23). Hovering alone doesn't animate: only the open dot.
    ("""      l.gfx
        .lineTo(linkData.target.x! + width / 2, linkData.target.y! + height / 2)
        .stroke({ alpha: l.alpha, width: 1, color: l.color })
""",
     """      const lit = l.active || selectedEdge(l)
      const tx = linkData.target.x! + width / 2
      const ty = linkData.target.y! + height / 2
      if (selectedEdge(l) && !twoWay(l)) {
        const k = currentTransform.k
        const sx = linkData.source.x! + width / 2
        const sy = linkData.source.y! + height / 2
        l.gfx.lineTo(tx, ty).stroke({ alpha: l.alpha * 0.3, width: 1.6 / k, color: l.color })
        const len = Math.hypot(tx - sx, ty - sy)
        if (len > 0) {
          // On screen: 6px dashes, 5px gaps, moving 12px a second.
          const dash = 6 / k
          const period = 11 / k
          const ux = (tx - sx) / len
          const uy = (ty - sy) / len
          // A new path: stroke() keeps the one it drew, and would draw the line again.
          l.gfx.beginPath()
          for (let d = ((time / 1000) * 12) / k % period - period; d < len; d += period) {
            const a = Math.max(d, 0)
            const b = Math.min(d + dash, len)
            if (b > a) l.gfx.moveTo(sx + ux * a, sy + uy * a).lineTo(sx + ux * b, sy + uy * b)
          }
          l.gfx.stroke({ alpha: l.alpha, width: 1.6 / k, color: l.color })
        }
      } else {
        l.gfx
          .lineTo(tx, ty)
          .stroke({ alpha: l.alpha * (lit ? 1 : 0.6), width: (lit ? 1.6 : 0.6) / currentTransform.k, color: l.color })
      }
      if (selectedEdge(l)) {
        const k = currentTransform.k
        const dx = linkData.target.x! - linkData.source.x!
        const dy = linkData.target.y! - linkData.source.y!
        const len = Math.hypot(dx, dy)
        if (len > 0) {
          const ux = dx / len
          const uy = dy / len
          // The tip on the target dot's rim; the head keeps its size on screen at any zoom.
          const back = nodeRadius(linkData.target) + 1 / k
          const tipX = tx - ux * back
          const tipY = ty - uy * back
          const baseX = tipX - (ux * 8) / k
          const baseY = tipY - (uy * 8) / k
          const half = 3.5 / k
          l.gfx
            .poly([tipX, tipY, baseX - uy * half, baseY + ux * half, baseX + uy * half, baseY - ux * half])
            .fill({ color: l.color, alpha: l.alpha })
        }
      }
"""),
    # Hover: the node and its links turn purple; the rest keep their look, without the
    # dimming Quartz applies to edges even with focusOnHover off (nodes: quartz.layout.ts).
    ("alpha = l.active ? 1 : 0.2",
     "alpha = 1"),
    ('l.color = l.active ? computedStyleMap["--gray"] : computedStyleMap["--lightgray"]',
     'l.color = l.active || selectedEdge(l) ? "#8b5cf6" : computedStyleMap["--lightgray"]'),
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
    # whose note is open stays purple (selectedNodeId) until the popover closes, and
    # so do its edges, whatever the pointer hovers meanwhile.
    ("  let hoveredNodeId: string | null = null\n",
     "  let hoveredNodeId: string | null = null\n"
     "  let selectedNodeId: string | null = null\n"
     "  const selectedEdge = (l: LinkRenderData) =>\n"
     "    selectedNodeId !== null &&\n"
     "    (l.simulationData.source.id === selectedNodeId || l.simulationData.target.id === selectedNodeId)\n"
     "  // A→B with B→A too: Quartz keeps them as two edges on the same line.\n"
     "  let edgeKeys: Set<string> | null = null\n"
     "  const twoWay = (l: LinkRenderData) => {\n"
     "    edgeKeys ??= new Set(linkRenderData.map((e) => `${e.simulationData.source.id}\\n${e.simulationData.target.id}`))\n"
     "    return edgeKeys.has(`${l.simulationData.target.id}\\n${l.simulationData.source.id}`)\n"
     "  }\n"),
    ('import { D3Config } from "../Graph"',
     'import { D3Config } from "../Graph"\n'
     'import "./tooltip.js"\n'
     'import { BadgeColors, NoteBadge, loadBadges, makeBadge } from "./graph-badges"\n'
     'import { TakeawayColors, TakeawayMark } from "./graph-takeaway"\n'
     'import { PaneGraph, connectGraph, disconnectGraph, dotShine, isSeen, onHostMachine, saveView, savedView, setShowHome, shineOf, showHome, starMode, toggleNote, toggleStar, toggleTakeaway, warmNote } from "./note-pane"\n'
     '// The black outline of a shining note\'s yellow label, over its burst. Every other\n'
     '// label has the same outline, invisible: an outline widens the text, and a label\n'
     '// gaining one when starred jumped down and pushed its star away (Victor, 2026-10-23).\n'
     'const SHINING_LABEL_STROKE = { color: "#000000", width: 2.5, join: "round" as const }\n'
     'const PLAIN_LABEL_STROKE = { ...SHINING_LABEL_STROKE, alpha: 0 }'),
    # PixiJS listens for pointermove on the whole document, so a pointer over the note
    # popover still lit the dot under it (Victor, 2026-10-14). Only a move over the canvas
    # reaches the dots; leaving it for the popover is the canvas's own pointerleave, which
    # unlights the dot. A move Pixi replays on document while the layout settles counts
    # where the pointer actually is.
    ("""  graph.appendChild(app.canvas)
""",
     """  graph.appendChild(app.canvas)
  const pixiEvents = app.renderer.events as unknown as { _onPointerMove: (e: PointerEvent) => void }
  const pixiMove = pixiEvents._onPointerMove
  document.removeEventListener("pointermove", pixiMove, true)
  pixiEvents._onPointerMove = (e: PointerEvent) => {
    const over = e.target === document ? document.elementFromPoint(e.clientX, e.clientY) : e.target
    if (over === app.canvas) pixiMove(e)
  }
  document.addEventListener("pointermove", pixiEvents._onPointerMove, true)
"""),
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
    # between them, as when hovering a dot. It rings the dot of the note the trainer
    # has open (Follow), and tells where every dot and its label are on screen (the
    # popover opens over the fewest unread ones).
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
    ring(id) {
      ringedNode = nodeRenderData.find((n) => n.simulationData.id === id) ?? null
    },
    shine() {
      const takeaways = new Set<string>()
      const shining = new Set<string>()
      const levels: Record<string, number> = {}
      for (const n of nodeRenderData) {
        const d = dotShine(n.simulationData.id)
        if (d.takeaway) takeaways.add(n.simulationData.id)
        if (d.level > 0) {
          shining.add(n.simulationData.id)
          levels[n.simulationData.id] = d.level
        }
        n.takeaway?.set(d)
        n.color = color(n.simulationData)
        n.label.style.fill = d.level > 0 ? takeawayColors.on : computedStyleMap["--dark"]
        n.label.style.stroke = d.level > 0 ? SHINING_LABEL_STROKE : PLAIN_LABEL_STROKE
      }
      starredIds = takeaways
      if (!dragging) renderPixiFromD3()
      // The canvas has no DOM: what it shows as starred, which dots draw a star beside
      // them and what each reads, and which ones shine, readable from a test.
      const ids = (keep: (n: NodeRenderData) => boolean) =>
        JSON.stringify(nodeRenderData.filter(keep).map((n) => n.simulationData.id))
      graph.dataset.takeaways = ids((n) => takeaways.has(n.simulationData.id))
      graph.dataset.starsShown = ids((n) => n.takeaway?.starShown ?? false)
      graph.dataset.shining = ids((n) => shining.has(n.simulationData.id))
      graph.dataset.levels = JSON.stringify(levels)
      graph.dataset.stars = JSON.stringify(
        Object.fromEntries(
          nodeRenderData.filter((n) => n.takeaway?.starShown).map((n) => [n.simulationData.id, n.takeaway!.starText]),
        ),
      )
    },
    dots() {
      const rect = app.canvas.getBoundingClientRect()
      return nodeRenderData.map((n) => {
        const box = n.gfx.getBounds()
        let { minX, minY, maxX, maxY } = box
        if (n.label.alpha > 0.3) {
          const label = n.label.getBounds()
          minX = Math.min(minX, label.minX)
          minY = Math.min(minY, label.minY)
          maxX = Math.max(maxX, label.maxX)
          maxY = Math.max(maxY, label.maxY)
        }
        return {
          id: n.simulationData.id,
          left: rect.left + minX,
          top: rect.top + minY,
          right: rect.left + maxX,
          bottom: rect.top + maxY,
        }
      })
    },
    dotAt(slug) {
      const n = nodeRenderData.find((n) => n.simulationData.id === slug)
      if (!n) return null
      const rect = app.canvas.getBoundingClientRect()
      const { minX, minY, maxX, maxY } = n.gfx.getBounds()
      return { x: rect.left + (minX + maxX) / 2, y: rect.top + (minY + maxY) / 2, r: (maxX - minX) / 2 }
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
  // Dragged dots and zoom back to the start: a fresh render lays the graph out the
  // same way every time (d3 seeds the positions deterministically).
  for (const container of containers) {
    if (container.querySelector(".graph-reset")) continue
    const reset = document.createElement("button")
    reset.className = "graph-reset"
    reset.textContent = "⟲ Reset layout"
    reset.addEventListener("click", () => {
      saveView(null) // back to fitting the whole graph in the window
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
      saveView(null) // the layout changes: the view left on the old one means nothing
      setShowHome(!showHome())
      home.classList.toggle("on", showHome())
      cleanupGlobalGraphs()
      void renderGlobalGraph()
    })
    // Top-right, as a list: what the wiki was written from (Victor, 2026-10-16; a line
    // along the bottom until 2026-10-21). "Zoom chat": its links and books, since 2026-10-22; "(if any)", as not every day has a Zoom (Victor, 2026-10-23).
    // "played shorts": the soundboard clips the room heard, linked on YouTube where they were fired (same day).
    const sources = document.createElement("div")
    sources.className = "graph-sources"
    const sourcesList = document.createElement("ul")
    for (const source of ["browser history", "opened files", "slides viewed", "notes", "transcription", "Zoom chat (if any)", "played shorts", "screenshots", "internet research"]) {
      sourcesList.appendChild(Object.assign(document.createElement("li"), { textContent: source }))
    }
    sources.append(Object.assign(document.createElement("div"), { textContent: "Sources" }), sourcesList)
    container.append(reset, home, sources)
    // Only on the trainer's machine, right of Home: the notes he opens here are the ones
    // his participants' Follow rings in yellow (Victor, 2026-10-16).
    if (onHostMachine()) {
      const followed = document.createElement("div")
      followed.className = "graph-followed"
      followed.textContent = "◉ Followed by participants"
      followed.dataset.tip = "The note you open here is ringed in yellow for everyone who ticks Follow"
      container.append(followed)
    }
  }
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
    # Best fit (Victor, 2026-10-12): once the layout settles, the full graph zooms and pans so
    # every dot and label is in the frame — embedded in a talk page, its edges fell outside.
    # Once per render: a dot dragged later must not make the whole view jump. Only without
    # a view the reader left (note-pane.ts savedView): a reload puts that one back at once
    # and stays put, it never zooms out on its own (Victor, 2026-10-21).
    ("""  if (enableZoom) {
    select<HTMLCanvasElement, NodeData>(app.canvas).call(
      zoom<HTMLCanvasElement, NodeData>()
""",
     """  const zoomBehavior = zoom<HTMLCanvasElement, NodeData>()
  if (enableZoom) {
    select<HTMLCanvasElement, NodeData>(app.canvas).call(
      zoomBehavior
"""),
    ("""  if (isGlobal) connectGraph(paneGraph)
""",
     """  const keptView = isGlobal && enableZoom ? savedView() : null
  if (isGlobal && enableZoom) {
    // The wheel zooms; a double-click doesn't (Victor, 2026-10-23): it opened a note and
    // zoomed in on it at once. d3 binds it on the canvas, as "dblclick.zoom".
    select<HTMLCanvasElement, NodeData>(app.canvas).on("dblclick.zoom", null)
    zoomBehavior.on("zoom.remember", (e: { transform: { x: number; y: number; k: number }; sourceEvent: unknown }) => {
      if (e.sourceEvent) saveView(e.transform) // the reader's own wheel, pinch or drag
    })
    if (keptView) {
      select<HTMLCanvasElement, NodeData>(app.canvas).call(
        zoomBehavior.transform,
        zoomIdentity.translate(keptView.x, keptView.y).scale(keptView.k),
      )
    }
    let fitted = keptView !== null
    simulation.on("end.fit", () => {
      if (fitted || stopAnimation) return
      fitted = true
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
      for (const n of nodeRenderData) {
        const { x, y } = n.simulationData
        if (x === undefined || y === undefined) continue
        const half = Math.max(n.radius, (n.label?.width ?? 0) / 2)
        x0 = Math.min(x0, x + width / 2 - Math.max(half, n.radius + 14))   // the picture left of the dot
        x1 = Math.max(x1, x + width / 2 + Math.max(half + 14, n.radius + 24))   // the badges, and the star after the label
        y0 = Math.min(y0, y + height / 2 - n.radius - 14)   // the badge sits above the dot
        y1 = Math.max(y1, y + height / 2 + n.radius + 2 + (n.label?.height ?? 0))
      }
      if (!isFinite(x0)) return
      const pad = 24
      const k = Math.min((width - 2 * pad) / (x1 - x0), (height - 2 * pad) / (y1 - y0), 1.6)
      const to = zoomIdentity.translate(width / 2 - k * (x0 + x1) / 2, height / 2 - k * (y0 + y1) / 2).scale(k)
      const from = currentTransform
      const start = performance.now()
      const step = (now: number) => {
        if (stopAnimation) return
        const t = Math.min((now - start) / 450, 1)
        const e = t * (2 - t)
        const lerp = (a: number, b: number) => a + (b - a) * e
        select<HTMLCanvasElement, NodeData>(app.canvas).call(
          zoomBehavior.transform,
          zoomIdentity.translate(lerp(from.x, to.x), lerp(from.y, to.y)).scale(lerp(from.k, to.k)),
        )
        if (t < 1) requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    })
  }
  if (isGlobal) connectGraph(paneGraph)
"""),
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
