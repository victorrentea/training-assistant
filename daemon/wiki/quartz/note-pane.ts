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
// opens on theirs too (see "Following the trainer" below).
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
  // Where the note's dot is on screen, or null when it has no dot (Home, hidden by
  // default) or the dot is out of view.
  position(slug: SimpleSlug): Point | null
}

type Point = { x: number; y: number }

// Where the popover opens: by the cursor (a clicked dot), where it already is (a
// link followed inside it), or by the note's dot (a note the trainer opened).
type Place = "cursor" | "keep" | "dot"

const parser = new DOMParser()
const cache = new Map<string, Promise<HTMLElement[]>>()

let graph: PaneGraph | null = null
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
  // The participant page sends the trainer's note once the graph can place it.
  if (!announced) {
    announced = true
    tellParent({ type: "wiki-ready" })
  }
}

// The d3 layout keeps moving the dots for a few seconds after a render: a note the
// trainer opened meanwhile moves next to where its dot came to rest.
export function graphSettled(g: PaneGraph) {
  if (g !== graph || !followPlaced || !peek || !peeked) return
  followPlaced = false
  placePeek(peek, g.position(peeked))
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
let followPlaced = false // placed by its dot while the layout may still be moving

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
  peek.addEventListener("mouseleave", () => highlight(null))
  // Being read: it no longer moves after its dot.
  peek.addEventListener("pointerdown", () => (followPlaced = false))
  peek.addEventListener("wheel", () => (followPlaced = false), { passive: true })
  // A link to another note swaps the popover to it instead of navigating away from
  // the graph. Stopped before it bubbles up to Quartz's SPA router, on window.
  body.addEventListener("click", (e) => {
    const slug = linkSlug(e.target)
    if (slug) {
      e.preventDefault()
      e.stopPropagation()
      void showPeek(slug, "keep", "user")
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

// Beside the point (the cursor, or a dot), flipped to its left where it would
// overflow the window. Where it fits on neither side (a phone: the popover is about
// as wide as the screen), below the point or above it, shortened to the room there
// if need be, so the dot stays in view. No point: centred. Inside the participant
// page it keeps clear of the top band, where the page floats its controls over the
// wiki: they would cover the popover's ✕.
function placePeek(el: HTMLElement, at: Point | null) {
  const gap = 16
  const top = embedded ? 72 : 8
  el.style.maxHeight = ""
  const w = el.offsetWidth
  let h = el.offsetHeight
  const clampX = (x: number) => Math.max(8, Math.min(x, innerWidth - 8 - w))
  const clampY = (y: number) => Math.max(top, Math.min(y, innerHeight - 8 - h))
  let x: number
  let y: number
  if (!at) {
    x = clampX((innerWidth - w) / 2)
    y = clampY((innerHeight - h) / 2)
  } else if (at.x + gap + w <= innerWidth - 8) {
    x = at.x + gap
    y = clampY(at.y + gap)
  } else if (at.x - gap - w >= 8) {
    x = at.x - gap - w
    y = clampY(at.y + gap)
  } else {
    x = clampX(at.x - w / 2)
    const below = innerHeight - 8 - (at.y + gap)
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

// By the cursor for a clicked dot; a link followed inside the popover keeps it where
// it is, under the mouse; a note the trainer opened goes by its dot.
async function showPeek(slug: SimpleSlug, place: Place, by: "user" | "follow") {
  const el = ensurePeek()
  graph?.select(slug)
  if (slug === peeked) return
  peeked = slug
  followPlaced = false
  reportOpenNote(slug)
  if (by === "user") tellParent({ type: "wiki-note-opened", slug })
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
  if (place === "dot") {
    placePeek(el, graph?.position(slug) ?? null)
    followPlaced = true
  } else if (place === "cursor" || !wasOpen) {
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
  body.querySelectorAll<HTMLAnchorElement>("a[data-slug]").forEach((a) => {
    a.classList.toggle("seen", isSeen(simplifySlug(a.dataset.slug as never)))
  })
}

// Also on a pan or scroll-zoom of the graph (patch-graph.py): its dot moves away from
// the popover, which would be left pointing at nothing.
export function hidePeek() {
  peeked = null
  followPlaced = false
  reportOpenNote(null)
  highlight(null)
  graph?.select(null)
  peek?.classList.remove("open")
}

// A click on a dot opens its note; on the open one, closes it.
export function toggleNote(slug: SimpleSlug) {
  if (slug === peeked) hidePeek()
  else void showPeek(slug, "cursor", "user")
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
let reported: SimpleSlug | null | undefined // the last note told to the daemon

function onHostMachine(): boolean {
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

// To the participant page around the wiki: the graph is ready, or the reader opened
// a note on their own (which unticks their Follow).
function tellParent(msg: { type: string; slug?: SimpleSlug }) {
  if (embedded) window.parent.postMessage(msg, window.location.origin)
}

// From the participant page: the note the trainer has open now (null: none).
window.addEventListener("message", (e) => {
  if (!embedded || e.source !== window.parent || e.origin !== window.location.origin) return
  const msg = e.data
  if (msg?.type !== "wiki-follow") return
  if (msg.slug === null) hidePeek()
  else if (typeof msg.slug === "string") void showPeek(msg.slug as SimpleSlug, "dot", "follow")
})

// Not while typing, e.g. in Quartz's search box, whose own Esc closes it.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return
  const target = e.target as HTMLElement | null
  if (target?.closest?.("input, textarea, [contenteditable]")) return
  if (zoomed) unzoom() // a zoomed picture goes first, the note stays
  else hidePeek()
})
