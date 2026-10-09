// The wiki is its graph: the full graph fills the whole window for good, and a note
// is only ever read in a popover by the cursor, like Obsidian's page preview. There
// is no side pane: it covered a third of the graph (Victor, 2026-10-09).
// Hovering a dot previews its note; the mouse can move into the popover to scroll it,
// and it goes away once the mouse leaves both the dot and the popover. A click on the
// dot pins it instead: its dot turns purple and the popover stays until Esc, a second
// click on that dot, or the next dot hovered. A link inside the note swaps the popover
// to that note in place (pinned), without ever leaving the graph; hovering one lights
// up its dot and the edge to it from the note shown.
// Every note shown counts as seen on this browser: its dot and the links to it dim,
// so what is left to read stands out.
//
// Copied next to graph.inline.ts by daemon/wiki/builder.py; patch-graph.py makes the
// full graph register here (connectGraph), call toggleNote() on a click and
// hoverDot() on hover.
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
}

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

export function connectGraph(g: PaneGraph) {
  graph = g
  g.select(pinned ? peeked : null)
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
let dot: SimpleSlug | null = null // the dot under the mouse
let peek: HTMLElement | null = null
let peeked: SimpleSlug | null = null // the note the popover shows
let pinned = false // clicked: stays when the mouse leaves
let hideTimer = 0

function ensurePeek(): HTMLElement {
  if (peek) return peek
  peek = document.createElement("div")
  peek.className = "note-peek"
  peek.innerHTML = `
    <h2 class="note-peek-title"></h2>
    <div class="note-peek-body"></div>`
  const body = peek.querySelector(".note-peek-body") as HTMLElement
  // The mouse in the popover has not "left the dot": it stays, to be scrolled.
  peek.addEventListener("mouseenter", () => clearTimeout(hideTimer))
  peek.addEventListener("mouseleave", () => {
    highlight(null)
    scheduleHide()
  })
  // A link to another note swaps the popover to it instead of navigating away from
  // the graph. Stopped before it bubbles up to Quartz's SPA router, on window.
  body.addEventListener("click", (e) => {
    const slug = linkSlug(e.target)
    if (slug) {
      e.preventDefault()
      e.stopPropagation()
      void showPeek(slug, true)
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

// Beside the cursor, flipped to its left where it would overflow the window.
function placePeek(el: HTMLElement) {
  const gap = 16
  let x = mouseX + gap
  if (x + el.offsetWidth > innerWidth - 8) x = Math.max(8, mouseX - gap - el.offsetWidth)
  const y = Math.max(8, Math.min(mouseY + gap, innerHeight - 8 - el.offsetHeight))
  el.style.left = `${x}px`
  el.style.top = `${y}px`
}

async function showPeek(slug: SimpleSlug, pin: boolean) {
  clearTimeout(hideTimer)
  const el = ensurePeek()
  const wasOpen = el.classList.contains("open")
  pinned = pin
  graph?.select(pin ? slug : null)
  if (slug === peeked) return
  peeked = slug
  highlight(null)
  const elts = await loadNote(slug).catch(() => null)
  if (peeked !== slug) return // the mouse moved on meanwhile
  showNote(
    el.querySelector(".note-peek-title") as HTMLElement,
    el.querySelector(".note-peek-body") as HTMLElement,
    elts,
  )
  el.classList.add("open")
  // A link followed inside the popover keeps it where it is, under the mouse.
  if (!wasOpen || dot === slug) placePeek(el)
  markSeen(slug)
  graph?.select(pinned ? slug : null) // repaints its dot, now seen
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

function hidePeek() {
  clearTimeout(hideTimer)
  peeked = null
  pinned = false
  highlight(null)
  graph?.select(null)
  peek?.classList.remove("open")
}

// A short grace, for the mouse to travel from the dot into the popover.
function scheduleHide() {
  clearTimeout(hideTimer)
  if (!pinned) hideTimer = window.setTimeout(hidePeek, 300)
}

export function hoverDot(slug: SimpleSlug | null) {
  dot = slug
  if (slug && slug !== peeked) void showPeek(slug, false)
  else if (!slug && peeked) scheduleHide()
}

// A click on a dot pins its note; on the pinned one, closes it.
export function toggleNote(slug: SimpleSlug) {
  if (pinned && slug === peeked) hidePeek()
  else void showPeek(slug, true)
}

document.addEventListener("pointermove", (e) => {
  mouseX = e.clientX
  mouseY = e.clientY
})

// Not while typing, e.g. in Quartz's search box, whose own Esc closes it.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return
  const target = e.target as HTMLElement | null
  if (target?.closest?.("input, textarea, [contenteditable]")) return
  if (zoomed) unzoom() // a zoomed picture goes first, the note stays
  else hidePeek()
})
