// The wiki is its graph: the full graph fills the whole window for good, and a note
// is only ever read in a popover by the cursor. There is no side pane: it covered a
// third of the graph (Victor, 2026-10-09). Only a click on a dot opens its note -
// popping up on hover got in the way of just looking at the graph (same day). Its dot
// lights up white and the popover stays until Esc, a second click on that dot, or a
// click on another dot. A link inside the note swaps the popover to that note in
// place, without ever leaving the graph; hovering one lights up its dot and the edge
// to it from the note shown.
// Every note shown counts as seen on this browser: its dot and the links to it dim,
// so what is left to read stands out. One edited since it was read gets a pulsing ✏️
// on its dot until it is opened again (see "Edited notes" below).
//
// Participants can follow the trainer: whichever note Victor opens on his machine
// gets a pulsing yellow ring around its dot on theirs (see "Following the trainer"
// below). He can also star a note as a key takeaway: its dot glows golden on every
// graph (see "Key takeaways" below), and so can the participants, for the notes they
// found interesting (see "Participants' stars" below).
//
// Copied next to graph.inline.ts by daemon/wiki/builder.py; patch-graph.py makes the
// full graph register here (connectGraph) and call toggleNote() on a click.
import { DotShine, StarMode, shineLevel } from "./graph-takeaway"
import {
  SimpleSlug,
  getFullSlug,
  normalizeRelativeURLs,
  pathToRoot,
  resolveRelative,
  simplifySlug,
} from "../../util/path"

export type PaneGraph = {
  select(slug: SimpleSlug | null): void
  highlight(slug: SimpleSlug | null): void
  // The yellow ring around the note the trainer has open (null: none).
  ring(slug: SimpleSlug | null): void
  // The trainer's takeaways or the participants' stars changed: every dot shines and
  // its star reads as dotShine() says.
  shine(): void
  // Every dot on screen, each with its label: what the popover should leave in view.
  dots(): Dot[]
  // Where a dot is on screen, its centre and radius (null: not in the graph).
  dotAt(slug: SimpleSlug): Circle | null
}

type Point = { x: number; y: number }
type Circle = Point & { r: number }
type Box = { left: number; top: number; right: number; bottom: number }
type Dot = Box & { id: SimpleSlug }

// Where the popover opens: by the cursor (a clicked dot), or where it already is (a
// link followed inside it).
type Place = "cursor" | "keep"

const parser = new DOMParser()
const cache = new Map<string, Promise<HTMLElement[]>>()

let graph: PaneGraph | null = null
let ringed: SimpleSlug | null = null // the note the trainer has open, for a follower
let highlighted: SimpleSlug | null = null

// Kept per site (the path holds the session id), so one training's reading doesn't
// grey out the next one's notes. Private windows or blocked storage just start over.
// Each note with the version read (builder.py's note-versions.json); "" for one read
// before versions existed, or before they loaded. A list of slugs is the old format.
const seenKey = () => `wiki-seen:${new URL(pathToRoot(getFullSlug(window)), window.location.href).pathname}`
let seen: Map<string, string> | null = null

function seenNotes(): Map<string, string> {
  if (!seen) {
    try {
      const stored = JSON.parse(localStorage.getItem(seenKey()) ?? "{}")
      seen = new Map(
        Array.isArray(stored)
          ? stored.map((slug: string) => [slug, ""])
          : Object.entries(stored).filter((e): e is [string, string] => typeof e[1] === "string"),
      )
    } catch {
      seen = new Map()
    }
  }
  return seen
}

function saveSeen() {
  try {
    localStorage.setItem(seenKey(), JSON.stringify(Object.fromEntries(seenNotes())))
  } catch {}
}

export function isSeen(slug: string): boolean {
  return seenNotes().has(slug)
}

// Forgets every note read on this browser: all dots white again (the "Reset seen" pill,
// Victor, 2026-10-23).
export function resetSeen() {
  seen = new Map()
  try {
    localStorage.removeItem(seenKey())
  } catch {}
}

function markSeen(slug: SimpleSlug) {
  const notes = seenNotes()
  const version = versions?.get(slug) ?? ""
  if (notes.has(slug) && notes.get(slug) === version) return
  notes.set(slug, version)
  saveSeen()
}

// ── Edited notes ──
// The summarizer rewrites notes during the day. A note read here whose version changed
// since gets a ✏️ pulsing on its dot (graph-badges.ts EditPencil), on every browser
// that read it, until it is opened there again (Victor, 2026-10-26). A note not read
// yet needs none: its dot is still white.
let versions: Map<string, string> | null = null

function loadVersions() {
  const url = new URL(`${pathToRoot(getFullSlug(window))}/note-versions.json`, window.location.href)
  fetch(url)
    .then((res) => (res.ok ? res.json() : {}))
    .catch(() => ({})) // a site built before versions: no pencils
    .then((json: Record<string, unknown>) => {
      versions = new Map(
        Object.entries(json)
          .filter((e): e is [string, string] => typeof e[1] === "string")
          .map(([k, v]) => [simplifySlug(k as never), v]),
      )
      // A note read without a known version takes this one: from now on its edits show.
      const notes = seenNotes()
      let backfilled = false
      for (const [slug, read] of notes) {
        const now = versions.get(slug)
        if (read === "" && now) {
          notes.set(slug, now)
          backfilled = true
        }
      }
      if (backfilled) saveSeen()
    })
}

export function isEdited(slug: string): boolean {
  const read = seenNotes().get(slug)
  const now = versions?.get(slug)
  return !!read && !!now && read !== now
}

// Whether the full graph shows the Home dot (patch-graph.py's pill), remembered on
// this browser. Off by default: Home links to every note and hides the clusters.
const homeKey = "wiki-show-home"

export function showHome(): boolean {
  try {
    return localStorage.getItem(homeKey) === "1"
  } catch {
    return false
  }
}

export function setShowHome(show: boolean) {
  try {
    localStorage.setItem(homeKey, show ? "1" : "0")
  } catch {}
}

// Where the reader left the full graph's zoom and pan, remembered on this browser per
// site: a reload puts them back instead of zooming out to fit everything again (Victor,
// 2026-10-21). Only a zoom or pan of the reader's own is remembered; Reset layout and
// the Home pill forget it, and the graph fits itself to the window again.
export type View = { x: number; y: number; k: number }
const viewKey = () => `wiki-view:${new URL(pathToRoot(getFullSlug(window)), window.location.href).pathname}`

export function savedView(): View | null {
  try {
    const v = JSON.parse(localStorage.getItem(viewKey()) ?? "null")
    return v && [v.x, v.y, v.k].every((n) => typeof n === "number" && isFinite(n)) && v.k > 0 ? v : null
  } catch {
    return null
  }
}

export function saveView(v: View | null) {
  try {
    if (v) localStorage.setItem(viewKey(), JSON.stringify({ x: v.x, y: v.y, k: v.k }))
    else localStorage.removeItem(viewKey())
  } catch {}
}

function noteUrl(slug: SimpleSlug): URL {
  return new URL(resolveRelative(getFullSlug(window), slug), window.location.toString())
}

// The same content Quartz's own link popovers show (every `.popover-hint` of the
// page), minus the page chrome: breadcrumbs, Quartz's title (the note opens with
// its own H1) and the date line.
function loadNote(slug: SimpleSlug): Promise<HTMLElement[]> {
  const url = noteUrl(slug)
  const key = url.toString()
  let note = cache.get(key)
  if (!note) {
    note = fetch(key)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status}`)
        return res.text()
      })
      .then((text) => {
        const html = parser.parseFromString(text, "text/html")
        normalizeRelativeURLs(html, url)
        html.querySelectorAll("[id]").forEach((el) => (el.id = `note-peek-${el.id}`))
        html
          .querySelectorAll(".breadcrumb-container, .article-title, .content-meta")
          .forEach((el) => el.remove())
        return [...html.getElementsByClassName("popover-hint")] as HTMLElement[]
      })
    note.catch(() => cache.delete(key))
    cache.set(key, note)
  }
  return note
}

// Hovering a dot fetches its note already.
export function warmNote(slug: SimpleSlug) {
  loadNote(slug).catch(() => {})
}

let announced = false

export function connectGraph(g: PaneGraph) {
  graph = g
  if (!versions) loadVersions()
  g.select(peeked)
  g.ring(ringed)
  g.shine()
  // The participant page sends the trainer's note once the graph can place it.
  if (!announced) {
    announced = true
    tellParent({ type: "wiki-ready" })
  }
}

export function disconnectGraph(g: PaneGraph) {
  if (graph === g) graph = null
}

function linkSlug(target: EventTarget | null): SimpleSlug | null {
  const a = (target as Element | null)?.closest?.("a[data-slug]") as HTMLAnchorElement | null
  return a ? simplifySlug(a.dataset.slug as never) : null
}

function highlight(slug: SimpleSlug | null) {
  if (slug === highlighted) return
  highlighted = slug
  graph?.highlight(slug)
}

// A click on a picture in the note (a slide, a screenshot) blows it up over the whole
// window, to read its details, until Esc or a click on it. Never real browser
// fullscreen: leaving it would wreck the window layout the user had.
let zoomed: HTMLElement | null = null

function zoomImage(img: HTMLImageElement) {
  unzoom()
  const overlay = document.createElement("div")
  overlay.className = "note-zoom"
  overlay.appendChild(Object.assign(document.createElement("img"), { src: img.currentSrc || img.src, alt: img.alt }))
  overlay.addEventListener("click", unzoom)
  document.body.appendChild(overlay)
  zoomed = overlay
}

function unzoom() {
  if (!zoomed) return
  const overlay = zoomed
  zoomed = null
  overlay.remove()
}

function paragraph(text: string) {
  return Object.assign(document.createElement("p"), { textContent: text })
}

let mouseX = 0
let mouseY = 0
let peek: HTMLElement | null = null
let peeked: SimpleSlug | null = null // the note the popover shows
let placedBy: Point | null = null // where placePeek last put it from; null once dragged

function ensurePeek(): HTMLElement {
  if (peek) return peek
  peek = document.createElement("div")
  peek.className = "note-peek"
  // The ✕ is what a phone has instead of Esc or a second click on a tiny dot. The star
  // by the ✕ marks the note a key takeaway (the trainer's machine only).
  peek.innerHTML = `
    <button class="note-peek-close" type="button" aria-label="Close">✕</button>
    <div class="note-peek-head">
      <h2 class="note-peek-title"></h2>
      <button class="note-peek-star" type="button"></button>
    </div>
    <div class="note-peek-body"></div>`
  const body = peek.querySelector(".note-peek-body") as HTMLElement
  peek.querySelector(".note-peek-close")!.addEventListener("click", hidePeek)
  // Under the pointer an empty star fills: a preview of the click (Victor, 2026-10-23).
  const starButton = peek.querySelector(".note-peek-star") as HTMLButtonElement
  starButton.addEventListener("mouseenter", () => {
    if (!starButton.disabled) starButton.classList.add("hovered")
    showPeekStar()
  })
  starButton.addEventListener("mouseleave", () => {
    starButton.classList.remove("hovered")
    showPeekStar()
  })
  peek.querySelector(".note-peek-star")!.addEventListener("click", () => {
    if (!peeked) return
    if (starMode() === "voter") toggleStar(peeked, !mine.has(peeked))
    else toggleTakeaway(peeked, !starred.has(peeked))
  })
  dragByHead(peek, peek.querySelector(".note-peek-title") as HTMLElement)
  peek.addEventListener("mouseleave", () => highlight(null))
  // A link to another note swaps the popover to it instead of navigating away from
  // the graph. Stopped before it bubbles up to Quartz's SPA router, on window.
  body.addEventListener("click", (e) => {
    const slug = linkSlug(e.target)
    if (slug) {
      e.preventDefault()
      e.stopPropagation()
      void showPeek(slug, "keep")
      return
    }
    const img = (e.target as Element | null)?.closest?.("img")
    if (img) {
      e.preventDefault()
      e.stopPropagation()
      zoomImage(img as HTMLImageElement)
    }
  })
  body.addEventListener("mouseover", (e) => highlight(linkSlug(e.target)))
  // Opening the points (foldPoints) grows the popover: refit it to the window. A
  // details' toggle doesn't bubble, so it is caught on the way down.
  body.addEventListener("toggle", () => peek && fitPeek(peek), true)
  // A slide that loads after the popover was placed (preloadImages gave up on it) picks
  // its corner again: placed short, it took a bottom corner it no longer fits in, and
  // ran past the window's bottom edge with room to spare in a top one (Victor,
  // 2026-10-27). Dragged, it stays where it was dropped and only refits.
  body.addEventListener("load", () => peek && (placedBy ? placePeek(peek, placedBy) : fitPeek(peek)), true)
  document.body.appendChild(peek)
  return peek
}

// The title is a handle: dragged, it moves the popover off what it covers (Victor,
// 2026-10-14), half of it out of the window at most, its title always in. It stays
// where it was dropped for the links followed inside it; a click on a dot opens the
// next note by the cursor again.
function dragByHead(el: HTMLElement, head: HTMLElement) {
  head.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return
    e.preventDefault()
    placedBy = null
    const dx = e.clientX - el.offsetLeft
    const dy = e.clientY - el.offsetTop
    head.setPointerCapture(e.pointerId)
    document.getSelection()?.removeAllRanges()
    document.body.classList.add("peek-dragging")
    const move = (m: PointerEvent) => {
      el.style.left = `${Math.max(-el.offsetWidth / 2, Math.min(m.clientX - dx, innerWidth - el.offsetWidth / 2))}px`
      el.style.top = `${Math.max(0, Math.min(m.clientY - dy, innerHeight - 48))}px`
    }
    const drop = () => {
      document.body.classList.remove("peek-dragging")
      head.removeEventListener("pointermove", move)
      head.removeEventListener("pointerup", drop)
      head.removeEventListener("pointercancel", drop)
    }
    head.addEventListener("pointermove", move)
    head.addEventListener("pointerup", drop)
    head.addEventListener("pointercancel", drop)
  })
}

// In a top corner of the window, the one that hides the fewest dots (leastCovering).
// Where the window has hardly any room beside it (a phone: the popover is about as
// wide as the screen), below the cursor or above it, shortened to the room there if need
// be. Inside the participant page it keeps clear of the top band, where the page
// floats its controls over the wiki: they would cover the popover's ✕.
function placePeek(el: HTMLElement, at: Point) {
  placedBy = at
  const gap = 16
  const { top, bottom } = peekMargins()
  el.style.maxHeight = ""
  const w = el.offsetWidth
  let h = el.offsetHeight
  if (h > innerHeight - top - bottom) {
    h = innerHeight - top - bottom
    el.style.maxHeight = `${h}px`
  }
  const clampX = (x: number) => Math.max(8, Math.min(x, innerWidth - 8 - w))
  const clampY = (y: number) => Math.max(top, Math.min(y, innerHeight - bottom - h))
  let x: number
  let y: number
  if (innerWidth - w >= 200) {
    ;({ x, y } = leastCovering(at, w, h, top))
  } else {
    x = clampX(at.x - w / 2)
    const below = innerHeight - bottom - (at.y + gap)
    const above = at.y - gap - top
    if (h > below && h > above && Math.max(below, above) >= 200) {
      h = Math.max(below, above)
      el.style.maxHeight = `${h}px`
    }
    if (h <= below) y = at.y + gap
    else if (h <= above) y = at.y - gap - h
    else y = clampY(at.y + gap)
  }
  el.style.left = `${x}px`
  el.style.top = `${y}px`
}

// The room the popover keeps free at the window's top and bottom. Under 900px the
// participant page's emoji bar floats over the bottom of this frame: the note stops
// above it, shorter if need be, instead of sliding under it.
function peekMargins() {
  return { top: embedded ? 72 : 8, bottom: embedded && innerWidth < 900 ? 88 : 16 }
}

// Its points opened, the popover grows down from where it was placed for the lead
// alone: it ends above the window's bottom edge instead of running past it, which
// looked cut off (Victor, 2026-10-16). Shorter and scrolling where it stands, or moved
// up when the room left under it is too little to read in.
function fitPeek(el: HTMLElement) {
  const { top, bottom } = peekMargins()
  el.style.maxHeight = ""
  const h = el.offsetHeight
  const room = innerHeight - bottom - el.offsetTop
  if (h <= room) return
  if (room >= Math.min(h, 320)) {
    el.style.maxHeight = `${room}px`
    return
  }
  const y = Math.max(top, innerHeight - bottom - h)
  el.style.top = `${y}px`
  el.style.maxHeight = `${innerHeight - bottom - y}px`
}

// In the top corner of the window that hides the fewest dots, its own dot kept in view;
// between equally good corners, the one nearest its dot (Victor, 2026-10-23 - it was
// the spot nearest the cursor that hid the fewest unread dots and none of the open
// dot's edges, which put it somewhere new on every click). Never a bottom one: on a
// shared screen the call's own bars cover the bottom, and the room misses the note
// there (Victor, 2026-10-28).
function leastCovering(at: Point, w: number, h: number, top: number): Point {
  const dots = graph?.dots() ?? []
  const own = dots.find((d) => d.id === peeked)
  const near = own ? { x: (own.left + own.right) / 2, y: (own.top + own.bottom) / 2 } : at
  const overlaps = (b: Box, x: number, y: number) =>
    b.left < x + w && b.right > x && b.top < y + h && b.bottom > y
  const y = top
  let best = { x: 8, y }
  let bestScore = Infinity
  for (const x of [8, innerWidth - 8 - w]) {
    let score = Math.hypot(Math.max(x - near.x, 0, near.x - x - w), Math.max(y - near.y, 0, near.y - y - h))
    if (own && overlaps(own, x, y)) score += 1e7
    for (const d of dots) if (d !== own && overlaps(d, x, y)) score += 1e4
    if (score < bestScore) {
      bestScore = score
      best = { x, y }
    }
  }
  return best
}

// A soft beam from the open dot to its popover, under it, so the eye sees where the
// note comes from (Victor, 2026-10-23): the outline of the dot's disc and the
// popover's corners together, its sides tangent to the dot, strongest at the dot. Its
// edges stand out and fade inward to nothing in its middle: a wide blurred outline,
// clipped to the inside, under a thin crisp one (Victor, 2026-10-23). In the colour of the open dot's lit links,
// the text colour (white on dark); gold, like its burst, when the note shines. Redrawn
// every frame while the popover is open: the graph moves, zooms and gets dragged under it.
let beam: SVGSVGElement | null = null
let beamFrame = 0

function ensureBeam(): SVGSVGElement {
  if (beam) return beam
  const ns = "http://www.w3.org/2000/svg"
  beam = document.createElementNS(ns, "svg")
  beam.classList.add("note-beam")
  beam.innerHTML = `
    <defs><linearGradient id="note-beam-fill" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-opacity="0.35"/><stop offset="1" stop-opacity="0.08"/>
    </linearGradient><linearGradient id="note-beam-edge" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-opacity="0.5"/><stop offset="1" stop-opacity="0.12"/>
    </linearGradient>
    <clipPath id="note-beam-inside"><polygon/></clipPath>
    <filter id="note-beam-soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="9"/></filter></defs>
    <polygon fill="none" stroke="url(#note-beam-fill)" stroke-width="36" stroke-linejoin="round"
      clip-path="url(#note-beam-inside)" filter="url(#note-beam-soft)"/>
    <polygon fill="none" stroke="url(#note-beam-edge)" stroke-width="1.5" stroke-linejoin="round"/>`
  document.body.append(beam)
  return beam
}

function followWithBeam() {
  cancelAnimationFrame(beamFrame)
  const svg = ensureBeam()
  const draw = () => {
    const dot = peek?.classList.contains("open") && peeked ? graph?.dotAt(peeked) : null
    const box = peek?.getBoundingClientRect()
    const inside = dot && box && dot.x > box.left && dot.x < box.right && dot.y > box.top && dot.y < box.bottom
    svg.style.display = dot && box && !inside ? "" : "none"
    if (dot && box && !inside) {
      const corners = [
        [box.left, box.top],
        [box.right, box.top],
        [box.right, box.bottom],
        [box.left, box.bottom],
      ]
      // The dot's whole disc, not its centre: the beam's sides run tangent to it.
      const rim = Array.from({ length: 24 }, (_, i) => {
        const a = (i * Math.PI) / 12
        return [dot.x + dot.r * Math.cos(a), dot.y + dot.r * Math.sin(a)]
      })
      const points = hull([...rim, ...corners]).join(" ")
      svg.querySelectorAll("polygon").forEach((polygon) => polygon.setAttribute("points", points))
      const color = peek!.classList.contains("takeaway") ? "var(--wiki-takeaway)" : "var(--dark)"
      svg.querySelectorAll("linearGradient").forEach((gradient) => {
        // A style, not the stop-color attribute: an attribute doesn't read CSS variables.
        gradient.querySelectorAll("stop").forEach((stop) => (stop.style.stopColor = color))
        gradient.setAttribute("x1", `${dot.x}`)
        gradient.setAttribute("y1", `${dot.y}`)
        gradient.setAttribute("x2", `${(box.left + box.right) / 2}`)
        gradient.setAttribute("y2", `${(box.top + box.bottom) / 2}`)
      })
    }
    if (dot !== null && peek?.classList.contains("open")) beamFrame = requestAnimationFrame(draw)
    else svg.style.display = "none"
  }
  draw()
}

// The convex hull of a few points (Andrew's monotone chain), as "x,y" pairs.
function hull(points: number[][]): string[] {
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const cross = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const half = (pts: number[][]) => {
    const out: number[][] = []
    for (const p of pts) {
      while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop()
      out.push(p)
    }
    return out.slice(0, -1)
  }
  return [...half(sorted), ...half([...sorted].reverse())].map(([x, y]) => `${x},${y}`)
}

// By the cursor for a clicked dot; a link followed inside the popover keeps it where
// it is, under the mouse; a note the trainer opened goes by its dot.
async function showPeek(slug: SimpleSlug, place: Place) {
  const el = ensurePeek()
  graph?.select(slug)
  if (slug === peeked) return
  peeked = slug
  showPeekStar()
  reportOpenNote(slug)
  highlight(null)
  const elts = await loadNote(slug).catch(() => null)
  if (elts) await preloadImages(elts, 600)
  if (peeked !== slug) return // another note was picked meanwhile
  showNote(
    el.querySelector(".note-peek-title") as HTMLElement,
    el.querySelector(".note-peek-body") as HTMLElement,
    elts,
  )
  const wasOpen = el.classList.contains("open")
  el.classList.add("open")
  if (place === "cursor" || !wasOpen) {
    placePeek(el, { x: mouseX, y: mouseY })
  }
  followWithBeam()
  markSeen(slug)
  graph?.select(slug) // repaints its dot, now seen
}

// A note's slides arrive after its text: placed without them, the popover sat in a
// bottom corner and then grew past the window's bottom edge, to be dragged back up
// (Victor, 2026-10-26). It waits for them a moment before it is placed; one that comes
// later still refits it (the load listener in ensurePeek).
function preloadImages(elts: HTMLElement[], ms: number): Promise<void> {
  const loads = elts
    .flatMap((e) => [...e.querySelectorAll("img")])
    .map((img) => {
      const pre = new Image()
      pre.src = img.src
      return pre.decode().catch(() => {})
    })
  return Promise.race([Promise.all(loads), new Promise((r) => setTimeout(r, ms))]).then(() => {})
}

function showNote(title: HTMLElement, body: HTMLElement, elts: HTMLElement[] | null) {
  body.scrollTop = 0
  if (!elts || elts.length === 0) {
    title.textContent = ""
    body.replaceChildren(paragraph("Could not load this note."))
    return
  }
  const note = elts.map((e) => e.cloneNode(true) as HTMLElement)
  // The note's own H1 moves up into the head, which stays put while the body scrolls.
  const h1 = note.map((e) => (e.tagName === "H1" ? e : e.querySelector("h1"))).find(Boolean)
  title.innerHTML = h1?.innerHTML ?? ""
  h1?.remove()
  body.replaceChildren(...note.filter((e) => e !== h1))
  foldPoints(body)
  body.querySelectorAll<HTMLAnchorElement>("a[data-slug]").forEach((a) => {
    a.classList.toggle("seen", isSeen(simplifySlug(a.dataset.slug as never)))
  })
}

// Only the lead sentence shows at first; the bullets under it fold into a "More"
// line that opens them (Victor, 2026-10-14): at the end of the day there is no time
// to go through every note's points, and the lead is what the reader takes away.
// A note without a lead paragraph shows whole. Its slides stay out of the fold, between
// the lead and "More" (Victor, 2026-10-15): a picture is worth showing up front. So
// do its emotional anchors (⚓ *the story*, Victor, 2026-10-16), one line each: the
// story is what makes the point stick. Then its external links, one short line each, so
// the reader sees at once where to go (Victor, 2026-10-22); they stay in the points too.
function foldPoints(body: HTMLElement) {
  const article = body.querySelector("article")
  const lead = article?.firstElementChild
  if (!article || lead?.tagName !== "P" || !lead.nextElementSibling) return
  const rest: Element[] = []
  for (let e = lead.nextElementSibling; e; e = e.nextElementSibling) rest.push(e)
  // The note's own points: not the "See also" / day footer under its closing rule.
  const footer = rest.findIndex((e) => e.tagName === "HR")
  const own = rest.slice(0, footer < 0 ? rest.length : footer)
  // A slide is its own paragraph: ![[assets/…]] plus the *Slide N — …* caption under it.
  const slides = own.filter((e) => e.tagName === "P" && e.querySelector("img"))
  const anchors = own.flatMap((e) =>
    [...e.querySelectorAll("em")].filter((em) => em.previousSibling?.textContent?.trimEnd().endsWith("⚓")),
  )
  const lines = anchors.map((em) => {
    const line = document.createElement("p")
    line.className = "note-anchor"
    line.append("⚓ ", em.cloneNode(true))
    return line
  })
  const links = linkList(own)
  const details = document.createElement("details")
  details.className = "note-points"
  const summary = document.createElement("summary")
  summary.textContent = "More"
  details.append(summary, ...rest.filter((e) => !slides.includes(e)))
  article.append(...slides, ...lines, ...(links ? [links] : []), details)
}

// The note's external links as a short list, each behind a 🔗 (a 🎬 for a short played
// in the room): the note's own word for each (a link written as a bare URL shows its
// site instead), the full URL in its tooltip, and the site it goes to after an em dash,
// in grey (Victor, 2026-10-23) - not after a short: "youtu.be" says nothing there.
const SHORT = "\u{1F3AC}" // 🎬

// "…/docs/en/memory" → "memory", "…/wiki/Progressive_disclosure" → "Progressive
// disclosure"; the site when the address has no path.
function pageName(href: string, site: string): string {
  const last = new URL(href).pathname.split("/").filter(Boolean).pop() ?? ""
  const name = decodeURIComponent(last).replace(/\.[a-z]+$/i, "").replace(/[-_]+/g, " ").trim()
  return name || site
}

function linkList(own: Element[]): HTMLElement | null {
  const seenHrefs = new Set<string>()
  const items: HTMLElement[] = []
  for (const a of own.flatMap((e) => [...e.querySelectorAll<HTMLAnchorElement>("a.external")])) {
    if (seenHrefs.has(a.href)) continue
    seenHrefs.add(a.href)
    let site: string
    try {
      site = new URL(a.href).hostname.replace(/^www\./, "")
    } catch {
      continue
    }
    const short = a.textContent?.includes(SHORT) ?? false
    const text = (a.textContent ?? "").replace(SHORT, "").trim()
    const link = document.createElement("a")
    link.className = "external"
    link.href = a.href
    link.target = "_blank"
    link.rel = "noopener"
    link.dataset.tip = a.href
    // A number or a scrap of a word says nothing out of its sentence ("200"): the
    // page's own name from its address instead (Victor, 2026-10-23).
    const meaningless = /^[\d\s.,%$€]+$/.test(text) || text.length <= 2
    link.textContent = !text || /^https?:|^www\./.test(text) || text === site ? site : meaningless ? pageName(a.href, site) : text
    const item = document.createElement("li")
    if (short) item.className = "short"
    item.append(link)
    if (link.textContent !== site && !short) {
      item.append(Object.assign(document.createElement("span"), { className: "note-link-site", textContent: ` — ${site}` }))
    }
    items.push(item)
  }
  if (items.length === 0) return null
  const list = document.createElement("ul")
  list.className = "note-links"
  list.append(...items)
  return list
}

// Not on a pan or zoom of the graph: the note being read stays open while the reader
// zooms in around it (Victor, 2026-10-16), and can be dragged off what it covers.
export function hidePeek() {
  peeked = null
  reportOpenNote(null)
  highlight(null)
  graph?.select(null)
  peek?.classList.remove("open")
}

// A click on a dot opens its note; on the open one, closes it.
export function toggleNote(slug: SimpleSlug) {
  if (slug === peeked) hidePeek()
  else void showPeek(slug, "cursor")
}

// pointerdown too: a tap on a phone moves no pointer before it lands.
const trackPointer = (e: PointerEvent) => {
  mouseX = e.clientX
  mouseY = e.clientY
}
document.addEventListener("pointermove", trackPointer)
document.addEventListener("pointerdown", trackPointer, { capture: true })

// ── Following the trainer ──
// Mirrors the Summary's Follow (static/participant.html):
//   trainer's machine: this pane → POST 127.0.0.1:1234/wiki/note → daemon → `wiki_note`
//   broadcast → each participant page → postMessage("wiki-follow") → this pane.
// The trainer's wiki posts straight to its own daemon, so following works whether he
// shows the wiki in the participant page's Wiki tab or in a tab of its own. Only a
// browser on the trainer's machine reaches 127.0.0.1:1234 (the daemon's CORS lets
// this origin in and answers Chrome's Private-Network-Access preflight); the
// ON_HOST_MACHINE cookie only spares every other browser a pointless request.
const HOST_DAEMON = "http://127.0.0.1:1234"
const embedded = window.parent !== window
// For custom.scss: the participant page floats its controls over the embedded wiki.
if (embedded) document.documentElement.classList.add("wiki-embedded")
let reported: SimpleSlug | null | undefined // the last note told to the daemon

export function onHostMachine(): boolean {
  return document.cookie.split(";").some((p) => p.trim() === "ON_HOST_MACHINE=true")
}

function reportOpenNote(slug: SimpleSlug | null) {
  if (slug === reported || !onHostMachine()) return
  reported = slug
  fetch(`${HOST_DAEMON}/wiki/note`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug }),
  }).catch(() => {
    reported = undefined // daemon restarting: the next open or close retries
  })
}

// To the participant page around the wiki: the graph is ready, or a star was clicked.
function tellParent(msg: { type: string; [key: string]: unknown }) {
  if (embedded) window.parent.postMessage(msg, window.location.origin)
}

// From the participant page: the note the trainer has open now (null: none, or the
// follower unticked Follow). Only ringed, never opened: the follower keeps exploring
// the graph and reading their own notes (Victor, 2026-10-16).
window.addEventListener("message", (e) => {
  if (!embedded || e.source !== window.parent || e.origin !== window.location.origin) return
  const msg = e.data
  // The notes the trainer starred (see "Key takeaways" below), on load and on change.
  if (msg?.type === "wiki-takeaways") {
    if (Array.isArray(msg.slugs)) applyTakeaways(msg.slugs.filter((s: unknown) => typeof s === "string"))
    return
  }
  // The participants' stars (see "Participants' stars" below).
  if (msg?.type === "wiki-stars") {
    applyStars(msg.counts, msg.mine)
    return
  }
  if (msg?.type !== "wiki-follow") return
  if (msg.slug !== null && typeof msg.slug !== "string") return
  ringed = msg.slug as SimpleSlug | null
  graph?.ring(ringed)
})

// Not while typing, e.g. in Quartz's search box, whose own Esc closes it.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return
  const target = e.target as HTMLElement | null
  if (target?.closest?.("input, textarea, [contenteditable]")) return
  if (zoomed) unzoom() // a zoomed picture goes first, the note stays
  else hidePeek()
})

// ── Key takeaways ──
// The trainer stars the notes his participants must leave with; on every graph their
// dots get a filled star and a golden glow (graph-takeaway.ts), live:
//   trainer's wiki (a star by a dot, or in the popover) → POST 127.0.0.1:1234/wiki/takeaway
//   → daemon saves them in the session folder → `wiki_takeaways` broadcast (the whole
//   set) → each participant page → postMessage("wiki-takeaways") → this pane.
// Who is the trainer: the same as for Follow - the ON_HOST_MACHINE cookie shows the
// hollow stars, and only his browser reaches the daemon on 127.0.0.1 anyway.
// A wiki in a tab of its own has no participant page around it: it asks the daemon
// (through Railway) for the set on load, and again every few seconds. On the trainer's
// machine it asks his own daemon, every second or two: a participant's star shows up
// on his graph live (Victor, 2026-10-22), for no load on Railway.
const TAKEAWAYS_POLL_MS = 15000
const TRAINER_POLL_MS = 1500
let starred = new Set<SimpleSlug>()
let changedAt = 0 // the trainer's last click: an older answer must not undo it

function applyTakeaways(slugs: readonly string[]) {
  starred = new Set(slugs.map((s) => simplifySlug(s as never)))
  graph?.shine()
  showPeekStar()
}

// The popover's star, right after its title (Victor, 2026-10-23 - it was left of the
// ✕): the trainer's takeaway on his machine, the participant's own star in the
// participant page, just the count anywhere else. The count follows it, small and
// white, from two up, like the ×5 after a dot's 🔗: "★×3" (Victor, 2026-10-23 - it was
// "3×★" in gold, "1×★" for one), and takes in the trainer's takeaway, like the burst on
// the dot: his click shows at once as one more. The graph shows no count:
// the bigger burst says it. A shining note's popover glows gold, like its dot.
function showPeekStar() {
  const button = peek?.querySelector(".note-peek-star") as HTMLButtonElement | null
  if (!peek || !button) return
  const mode = starMode()
  const takeaway = peeked !== null && starred.has(peeked)
  const { count, mine: voted } = peeked !== null ? starsOf(peeked) : { count: 0, mine: false }
  const total = count + (takeaway ? 1 : 0)
  const own = mode === "trainer" ? takeaway : mode === "voter" ? voted : total > 0
  peek.classList.toggle("takeaway", peeked !== null && shineOf(peeked) > 0)
  const times = Object.assign(document.createElement("span"), { className: "note-peek-count", textContent: `×${total}` })
  const lit = own || button.classList.contains("hovered")
  button.replaceChildren(lit ? "★\uFE0E" : "☆\uFE0E", ...(total > 1 ? [times] : []))
  button.classList.toggle("on", own)
  button.hidden = mode === "viewer" && total === 0
  button.disabled = mode === "viewer"
  const people = count === 1 ? "1 participant starred it" : `${count} participants starred it`
  const tip =
    mode === "trainer"
      ? (takeaway ? "Key takeaway - click to un-star" : "Star as a key takeaway: it glows for everyone") +
        (count > 0 ? ` · ${people}` : "")
      : mode === "voter"
        ? voted
          ? `You starred it - click to un-star · ${people}`
          : "Star it if you found it interesting: it shines for everyone" + (count > 0 ? ` · ${people}` : "")
        : takeaway
          ? "Key takeaway" + (count > 0 ? ` · ${people}` : "")
          : people
  button.dataset.tip = tip
  button.setAttribute("aria-label", tip)
}

// The trainer's click, on a dot's star or in the popover: shown at once, then saved.
export function toggleTakeaway(slug: SimpleSlug, on: boolean) {
  if (!onHostMachine()) return
  const before = [...starred]
  changedAt = Date.now()
  applyTakeaways(on ? [...before, slug] : before.filter((s) => s !== slug))
  fetch(`${HOST_DAEMON}/wiki/takeaway`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug, starred: on }),
  })
    .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
    .then((json: { slugs: string[] }) => applyTakeaways(json.slugs))
    .catch(() => applyTakeaways(before)) // not saved: the star goes back
}

function participantApi(): URL {
  if (onHostMachine()) return new URL(`${HOST_DAEMON}/api/participant/`)
  const site = new URL(pathToRoot(getFullSlug(window)), window.location.href)
  return new URL("../api/participant/", site)
}

function fetchTakeaways() {
  const asked = Date.now()
  fetch(new URL("wiki/takeaways", participantApi()))
    .then((res) => (res.ok ? res.json() : null))
    .then((json: { slugs?: string[] } | null) => {
      if (json && Array.isArray(json.slugs) && asked > changedAt) applyTakeaways(json.slugs)
    })
    .catch(() => {})
  fetchStars()
}

// ── Participants' stars ──
// Participants star the notes they found interesting; on every graph, the trainer's
// included, those shine with the takeaways' gold starburst, in five levels as the stars
// pile up (graph-takeaway.ts), and the star by the dot shows how many did (Victor,
// 2026-10-21):
//   participant's wiki (a star by a dot, or in the popover) → postMessage("wiki-star")
//   → the participant page around it → POST /api/participant/wiki/star with its
//   X-Participant-ID → daemon saves it in the session folder → `wiki_stars` broadcast
//   (counts only, never who) → each participant page → postMessage("wiki-stars") → here.
// The daemon only counts a star from someone who joined (daemon/wiki/stars.py says why
// it can't be forged or stuffed), and answers every click with what was really saved.
// A wiki in a tab of its own - the link the trainer pastes in the chat - stars too,
// straight to the daemon, as the participant whose page left its UUID in this origin's
// localStorage. Until 2026-10-27 it only showed the counts: that evening 20 participants
// were on such a tab, and only the 4 in the participant page's Wiki tab could star.
// Without that UUID (never joined on this browser) it only shows the counts.
const PARTICIPANT_UUID_KEY = "workshop_participant_uuid" // participant.html's _myUUID
let starCounts = new Map<SimpleSlug, number>()
let mine = new Set<SimpleSlug>()

function participantId(): string | null {
  try {
    return localStorage.getItem(PARTICIPANT_UUID_KEY)
  } catch {
    return null // blocked storage
  }
}

export function starMode(): StarMode {
  if (onHostMachine()) return "trainer"
  return embedded || participantId() ? "voter" : "viewer"
}

export function starsOf(slug: SimpleSlug): { count: number; mine: boolean } {
  return { count: starCounts.get(slug) ?? 0, mine: mine.has(slug) }
}

// A dot's level of shine, 0 (none) to 5 (graph-takeaway.ts).
export function shineOf(slug: SimpleSlug): number {
  return shineLevel(starred.has(slug), starCounts.get(slug) ?? 0)
}

// Everything a dot's star and burst show (graph-takeaway.ts).
export function dotShine(slug: SimpleSlug): DotShine {
  return { takeaway: starred.has(slug), ...starsOf(slug), level: shineOf(slug) }
}

function applyStars(counts: unknown, own: unknown) {
  const next = new Map<SimpleSlug, number>()
  if (counts && typeof counts === "object") {
    for (const [slug, n] of Object.entries(counts as Record<string, unknown>)) {
      if (typeof n === "number" && Number.isInteger(n) && n > 0) next.set(simplifySlug(slug as never), n)
    }
  }
  starCounts = next
  if (Array.isArray(own)) {
    mine = new Set(own.filter((s): s is string => typeof s === "string").map((s) => simplifySlug(s as never)))
    showStarHint()
  }
  graph?.shine()
  showPeekStar()
}

// The participant's click, on a dot's star or in the popover: shown at once, then sent
// to the page around the wiki, or straight to the daemon from a tab of its own; either
// answers with what was saved.
export function toggleStar(slug: SimpleSlug, on: boolean) {
  if (starMode() !== "voter") return
  const counts = Object.fromEntries(starCounts)
  if (on !== mine.has(slug)) counts[slug] = Math.max(0, (counts[slug] ?? 0) + (on ? 1 : -1))
  if (on && starHint) celebrate(starHint)
  applyStars(counts, on ? [...mine, slug] : [...mine].filter((s) => s !== slug))
  if (embedded) tellParent({ type: "wiki-star", slug, starred: on })
  else sendStar(slug, on)
}

// A tab of its own sends its clicks one at a time, in click order: sent together, a
// quick star-unstar overtakes itself on the way and the daemon keeps the wrong one
// (load test, 2026-10-27: a third of such double clicks ended reversed). Only the last
// answer is shown, so the star doesn't flicker through the ones before it; while any is
// on its way, the poll leaves the stars alone.
let starQueue: Promise<void> = Promise.resolve()
let starsInFlight = 0
let starClickedAt = 0

type StarsAnswer = { counts?: unknown; mine?: unknown } | null

function sendStar(slug: SimpleSlug, on: boolean) {
  const id = participantId()
  if (!id) return
  starClickedAt = Date.now()
  starsInFlight++
  starQueue = starQueue.then(() =>
    fetch(new URL("wiki/star", participantApi()), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Participant-ID": id },
      body: JSON.stringify({ slug, starred: on }),
    })
      .then((res) => (res.ok ? (res.json() as Promise<StarsAnswer>) : null))
      .catch(() => null)
      .then((json) => {
        if (--starsInFlight > 0) return
        if (json) applyStars(json.counts, json.mine)
        else fetchStars() // not saved: the wiki shows what is really stored
      }),
  )
}

function fetchStars() {
  const asked = Date.now()
  const id = onHostMachine() ? null : participantId()
  fetch(new URL("wiki/stars", participantApi()), { headers: id ? { "X-Participant-ID": id } : {} })
    .then((res) => (res.ok ? (res.json() as Promise<StarsAnswer>) : null))
    .then((json) => {
      if (!json || starsInFlight > 0 || asked < starClickedAt) return
      applyStars(json.counts, starMode() === "voter" ? json.mine : [])
    })
    .catch(() => {})
}

// After the stars' state above: the first poll reads it.
if (!embedded) {
  fetchTakeaways()
  window.setInterval(
    () => {
      if (document.visibilityState === "visible") fetchTakeaways()
    },
    onHostMachine() ? TRAINER_POLL_MS : TAKEAWAYS_POLL_MS,
  )
}

// A participant who hasn't starred anything yet sees a gold pill at the graph's
// bottom-right, "Please star your favorites", a sweep of light crossing it now and then.
// Their first star throws confetti from it toward the middle of the wiki and the pill
// goes for good; someone who already starred never sees it (Victor, 2026-10-23). Shown
// only once the page around the wiki has said which stars are theirs.
let starHint: HTMLElement | null = null
let starHintDone = false

function showStarHint() {
  if (starMode() !== "voter" || starHintDone) return
  if (mine.size > 0) {
    starHintDone = true
    starHint?.remove()
    starHint = null
    return
  }
  if (starHint) return
  starHint = Object.assign(document.createElement("div"), {
    className: "graph-star-hint",
    textContent: "☆\uFE0E Please star your favorites",
  })
  document.body.append(starHint)
}

function celebrate(hint: HTMLElement) {
  starHintDone = true
  starHint = null
  const from = hint.getBoundingClientRect()
  const x0 = from.left + from.width / 2
  const y0 = from.top + from.height / 2
  const colors = ["#fbbf24", "#f59e0b", "#fde68a", "#22c55e", "#ffffff"]
  for (let i = 0; i < 48; i++) {
    const bit = document.createElement("div")
    bit.className = "graph-confetti"
    bit.style.left = `${x0}px`
    bit.style.top = `${y0}px`
    bit.style.background = colors[i % colors.length]
    document.body.append(bit)
    // Toward the middle of the window, fanned out, each a little short or long of it.
    const dx = (innerWidth / 2 - x0) * (0.5 + Math.random()) + (Math.random() - 0.5) * innerWidth * 0.5
    const dy = (innerHeight / 2 - y0) * (0.5 + Math.random()) + (Math.random() - 0.5) * innerHeight * 0.5
    const spin = (Math.random() - 0.5) * 1440
    bit
      .animate(
        [
          { transform: "translate(0, 0) rotate(0deg)", opacity: 1 },
          { transform: `translate(${dx}px, ${dy}px) rotate(${spin}deg)`, opacity: 1, offset: 0.75 },
          { transform: `translate(${dx}px, ${dy + 60}px) rotate(${spin * 1.3}deg)`, opacity: 0 },
        ],
        { duration: 1400 + Math.random() * 600, easing: "cubic-bezier(0.2, 0.7, 0.3, 1)" },
      )
      .finished.then(() => bit.remove())
  }
  hint.animate([{ opacity: 1 }, { opacity: 0, transform: "scale(1.15)" }], { duration: 500, fill: "forwards" })
    .finished.then(() => hint.remove())
}
