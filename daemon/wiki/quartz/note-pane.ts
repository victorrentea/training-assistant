// The wiki is its graph: the full graph fills the whole window for good, and a note
// is only ever read in a popover by the cursor. There is no side pane: it covered a
// third of the graph (Victor, 2026-10-09). Only a click on a dot opens its note -
// popping up on hover got in the way of just looking at the graph (same day). Its dot
// turns purple and the popover stays until Esc, a second click on that dot, or a
// click on another dot. A link inside the note swaps the popover to that note in
// place, without ever leaving the graph; hovering one lights up its dot and the edge
// to it from the note shown.
// Every note shown counts as seen on this browser: its dot and the links to it dim,
// so what is left to read stands out.
//
// Participants can follow the trainer: whichever note Victor opens on his machine
// gets a pulsing yellow ring around its dot on theirs (see "Following the trainer"
// below).
//
// Copied next to graph.inline.ts by daemon/wiki/builder.py; patch-graph.py makes the
// full graph register here (connectGraph) and call toggleNote() on a click.
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
  // Every dot on screen, each with its label: what the popover should leave in view.
  dots(): Dot[]
}

type Point = { x: number; y: number }
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
const seenKey = () => `wiki-seen:${new URL(pathToRoot(getFullSlug(window)), window.location.href).pathname}`
let seen: Set<string> | null = null

function seenNotes(): Set<string> {
  if (!seen) {
    try {
      seen = new Set(JSON.parse(localStorage.getItem(seenKey()) ?? "[]"))
    } catch {
      seen = new Set()
    }
  }
  return seen
}

export function isSeen(slug: string): boolean {
  return seenNotes().has(slug)
}

function markSeen(slug: SimpleSlug) {
  const notes = seenNotes()
  if (notes.has(slug)) return
  notes.add(slug)
  try {
    localStorage.setItem(seenKey(), JSON.stringify([...notes]))
  } catch {}
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
  g.select(peeked)
  g.ring(ringed)
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

function ensurePeek(): HTMLElement {
  if (peek) return peek
  peek = document.createElement("div")
  peek.className = "note-peek"
  // The ✕ is what a phone has instead of Esc or a second click on a tiny dot.
  peek.innerHTML = `
    <button class="note-peek-close" type="button" aria-label="Close">✕</button>
    <h2 class="note-peek-title"></h2>
    <div class="note-peek-body"></div>`
  const body = peek.querySelector(".note-peek-body") as HTMLElement
  peek.querySelector(".note-peek-close")!.addEventListener("click", hidePeek)
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
    const dx = e.clientX - el.offsetLeft
    const dy = e.clientY - el.offsetTop
    head.setPointerCapture(e.pointerId)
    const move = (m: PointerEvent) => {
      el.style.left = `${Math.max(-el.offsetWidth / 2, Math.min(m.clientX - dx, innerWidth - el.offsetWidth / 2))}px`
      el.style.top = `${Math.max(0, Math.min(m.clientY - dy, innerHeight - 48))}px`
    }
    const drop = () => {
      head.removeEventListener("pointermove", move)
      head.removeEventListener("pointerup", drop)
      head.removeEventListener("pointercancel", drop)
    }
    head.addEventListener("pointermove", move)
    head.addEventListener("pointerup", drop)
    head.addEventListener("pointercancel", drop)
  })
}

// Wherever it hides the fewest unread dots, keeping its own dot in view (Victor,
// 2026-10-15: pinned beside the cursor, it sat on a crowded corner of the graph while
// the top of the window was empty). Among equally good spots, the nearest to the
// cursor. Where it fits on neither side of the cursor (a phone: the popover is about
// as wide as the screen), below it or above it, shortened to the room there if need
// be. Inside the participant page it keeps clear of the top band, where the page
// floats its controls over the wiki: they would cover the popover's ✕.
function placePeek(el: HTMLElement, at: Point) {
  const gap = 16
  const top = embedded ? 72 : 8
  // Under 900px the participant page's emoji bar floats over the bottom of this
  // frame: the note stops above it, shorter if need be, instead of sliding under it.
  const bottom = embedded && innerWidth < 900 ? 88 : 8
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
  if (at.x + gap + w <= innerWidth - 8 || at.x - gap - w >= 8) {
    ;({ x, y } = leastCovering(at, w, h, top, bottom, gap))
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

// Scans the window for the top-left corner where a w×h popover covers the fewest
// dots: an unread one weighs as much as moving the popover 4000px further from the
// point, a read one 400px. Never over the point itself, nor over the open note's dot.
function leastCovering(at: Point, w: number, h: number, top: number, bottom: number, gap: number): Point {
  const dots = graph?.dots() ?? []
  const own = dots.find((d) => d.id === peeked)
  const keepClear = (own ? [own] : []).concat({
    left: at.x - gap,
    top: at.y - gap,
    right: at.x + gap,
    bottom: at.y + gap,
  })
  const others = dots.filter((d) => d !== own)
  const overlaps = (b: Box, x: number, y: number) =>
    b.left < x + w && b.right > x && b.top < y + h && b.bottom > y
  const steps = (lo: number, hi: number) => {
    const vs: number[] = []
    for (let v = lo; v < hi; v += 24) vs.push(v)
    vs.push(Math.max(lo, hi))
    return vs
  }
  // Beside the point, as it always opened: these win a tie on distance.
  const beside = [at.x + gap, at.x - gap - w].map((x) => ({ x, y: at.y + gap }))
  let best: Point | null = null
  let bestScore = Infinity
  for (const c of [
    ...beside,
    ...steps(8, innerWidth - 8 - w).flatMap((x) => steps(top, innerHeight - bottom - h).map((y) => ({ x, y }))),
  ]) {
    const x = Math.max(8, Math.min(c.x, innerWidth - 8 - w))
    const y = Math.max(top, Math.min(c.y, innerHeight - bottom - h))
    if (keepClear.some((b) => overlaps(b, x, y))) continue
    let score = Math.hypot(Math.max(x - at.x, 0, at.x - x - w), Math.max(y - at.y, 0, at.y - y - h))
    for (const d of others) if (overlaps(d, x, y)) score += isSeen(d.id) ? 400 : 4000
    if (score < bestScore) {
      bestScore = score
      best = { x, y }
    }
  }
  return best ?? { x: at.x + gap <= innerWidth - 8 - w ? at.x + gap : at.x - gap - w, y: at.y + gap }
}

// By the cursor for a clicked dot; a link followed inside the popover keeps it where
// it is, under the mouse; a note the trainer opened goes by its dot.
async function showPeek(slug: SimpleSlug, place: Place) {
  const el = ensurePeek()
  graph?.select(slug)
  if (slug === peeked) return
  peeked = slug
  reportOpenNote(slug)
  highlight(null)
  const elts = await loadNote(slug).catch(() => null)
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
  markSeen(slug)
  graph?.select(slug) // repaints its dot, now seen
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

// Only the lead sentence shows at first; the bullets under it fold into a "Details"
// line that opens them (Victor, 2026-10-14): at the end of the day there is no time
// to go through every note's points, and the lead is what the reader takes away.
// A note without a lead paragraph shows whole. Its slides stay out of the fold, between
// the lead and "Details" (Victor, 2026-10-15): a picture is worth showing up front.
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
  const points = own.reduce((n, e) => n + (e.matches("ul, ol") ? e.children.length : 0), 0)
  const details = document.createElement("details")
  details.className = "note-points"
  const summary = document.createElement("summary")
  summary.textContent = points > 0 ? `Details · ${points} point${points === 1 ? "" : "s"}` : "Details"
  details.append(summary, ...rest.filter((e) => !slides.includes(e)))
  article.append(...slides, details)
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

// To the participant page around the wiki: the graph is ready.
function tellParent(msg: { type: string }) {
  if (embedded) window.parent.postMessage(msg, window.location.origin)
}

// From the participant page: the note the trainer has open now (null: none, or the
// follower unticked Follow). Only ringed, never opened: the follower keeps exploring
// the graph and reading their own notes (Victor, 2026-10-16).
window.addEventListener("message", (e) => {
  if (!embedded || e.source !== window.parent || e.origin !== window.location.origin) return
  const msg = e.data
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
