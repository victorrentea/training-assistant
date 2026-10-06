// The wiki is its graph: the full graph fills the whole window for good, and this
// pane, floating over its right third, shows the selected note (Home at start).
// Clicking a dot, or a link inside the note, selects that note: its dot turns
// purple and the pane swaps in place, without ever leaving the graph. Hovering a
// link in the note lights up its dot and the edge to it from the selected note.
// Every note shown here counts as seen on this browser: its dot and the links to it
// dim, so what is left to read stands out.
// Esc, or a second click on the selected dot, closes the note and deselects the dot:
// the pane goes away, uncovering the rest of the graph. The next click on a dot opens
// a note again. Neither moves the graph: only a render (page load, window resize,
// Reset layout) centres it, on the part of the window the pane leaves free.
// Holding ⌘ (Ctrl off a Mac) over a dot previews its note in a popover by the cursor,
// like Obsidian's page preview, without touching the pane: the mouse can move into
// it to scroll, and it goes away once the mouse leaves both the dot and the popover.
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
let selected: SimpleSlug | null = null
let highlighted: SimpleSlug | null = null
let pane: HTMLElement | null = null

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
        html.querySelectorAll("[id]").forEach((el) => (el.id = `note-pane-${el.id}`))
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

// Hovering a dot fetches its note already, so the click shows it at once.
export function warmNote(slug: SimpleSlug) {
  loadNote(slug).catch(() => {})
}

export function connectGraph(g: PaneGraph) {
  graph = g
  if (selected) g.select(selected)
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

function ensurePane(): HTMLElement {
  if (pane) return pane
  pane = document.createElement("aside")
  pane.className = "note-pane"
  pane.innerHTML = `
    <h1 class="note-pane-title"></h1>
    <div class="note-pane-body"></div>`
  const body = pane.querySelector(".note-pane-body") as HTMLElement
  // A link to another note selects it here instead of navigating away from the graph.
  // Stopped before it bubbles up to Quartz's SPA router, which listens on window.
  body.addEventListener("click", (e) => {
    const slug = linkSlug(e.target)
    if (slug) {
      e.preventDefault()
      e.stopPropagation()
      selectNote(slug)
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
  body.addEventListener("mouseleave", () => highlight(null))
  document.body.appendChild(pane)
  return pane
}

// A click on a picture in the note (a slide, a screenshot) blows it up over the whole
// window, to read its details, until Esc or a click on it. Never real browser
// fullscreen: leaving it would wreck the window layout the user had.
let zoomed: HTMLElement | null = null

function zoomImage(img: HTMLImageElement) {
  unzoom()
  const overlay = document.createElement("div")
  overlay.className = "note-pane-zoom"
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

// The class sits on <html>, where custom.scss hides the pane.
const isClosed = () => document.documentElement.classList.contains("note-closed")

function setClosed(closed: boolean) {
  document.documentElement.classList.toggle("note-closed", closed)
}

// How much of the window's right side the pane hides, so a graph render centres
// itself on the rest (patch-graph.py). A page load renders the graph before or after
// the first note opens, so the pane is made here if need be: it is about to show.
export function paneCover(): number {
  return isClosed() ? 0 : ensurePane().offsetWidth
}

export function closeNote() {
  if (!pane || isClosed()) return
  selected = null
  highlight(null)
  graph?.select(null)
  setClosed(true)
}

// A click on a dot: the selected one closes the pane, any other one selects its note.
export function toggleNote(slug: SimpleSlug) {
  if (slug === selected && pane && !isClosed()) closeNote()
  else void selectNote(slug)
}

export async function selectNote(slug: SimpleSlug) {
  selected = slug
  markSeen(slug)
  highlight(null)
  graph?.select(slug)

  const pane = ensurePane()
  setClosed(false)
  const title = pane.querySelector(".note-pane-title") as HTMLElement
  const body = pane.querySelector(".note-pane-body") as HTMLElement
  const elts = await loadNote(slug).catch(() => null)
  if (selected !== slug) return // another note was picked meanwhile
  showNote(title, body, elts)
}

// Into the pane or the ⌘-hover popover, which share the same head-and-body shape.
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

// ── ⌘-hover preview ──
let mouseX = 0
let mouseY = 0
let modifierDown = false // ⌘, or Ctrl off a Mac
let dot: SimpleSlug | null = null // the dot under the mouse
let peek: HTMLElement | null = null
let peeked: SimpleSlug | null = null // the note the popover shows
let hideTimer = 0

function ensurePeek(): HTMLElement {
  if (peek) return peek
  peek = document.createElement("div")
  peek.className = "note-peek"
  peek.innerHTML = `
    <h2 class="note-peek-title" title="Open in the side pane"></h2>
    <div class="note-peek-body"></div>`
  // The mouse in the popover has not "left the dot": it stays, to be scrolled.
  peek.addEventListener("mouseenter", () => clearTimeout(hideTimer))
  peek.addEventListener("mouseleave", scheduleHide)
  // Its title, or a link in it, opens that note in the pane, like a click on its dot.
  peek.addEventListener("click", (e) => {
    const onTitle = !!(e.target as Element | null)?.closest?.(".note-peek-title")
    const slug = linkSlug(e.target) ?? (onTitle ? peeked : null)
    if (slug) {
      e.preventDefault()
      e.stopPropagation()
      hidePeek()
      void selectNote(slug)
      return
    }
    const img = (e.target as Element | null)?.closest?.("img")
    if (img) {
      e.preventDefault()
      e.stopPropagation()
      zoomImage(img as HTMLImageElement)
    }
  })
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

async function showPeek(slug: SimpleSlug) {
  clearTimeout(hideTimer)
  if (slug === peeked) return
  peeked = slug
  const el = ensurePeek()
  const elts = await loadNote(slug).catch(() => null)
  if (peeked !== slug) return // the mouse moved on meanwhile
  showNote(
    el.querySelector(".note-peek-title") as HTMLElement,
    el.querySelector(".note-peek-body") as HTMLElement,
    elts,
  )
  el.classList.add("open")
  placePeek(el)
  markSeen(slug)
  graph?.select(selected) // repaints its dot, now seen
}

function hidePeek() {
  clearTimeout(hideTimer)
  peeked = null
  peek?.classList.remove("open")
}

// A short grace, for the mouse to travel from the dot into the popover.
function scheduleHide() {
  clearTimeout(hideTimer)
  hideTimer = window.setTimeout(hidePeek, 300)
}

export function hoverDot(slug: SimpleSlug | null) {
  dot = slug
  if (slug && modifierDown) void showPeek(slug)
  else if (peeked) scheduleHide()
}

document.addEventListener("pointermove", (e) => {
  mouseX = e.clientX
  mouseY = e.clientY
  modifierDown = e.metaKey || e.ctrlKey
})
// ⌘ pressed while already resting on a dot previews it too, as in Obsidian.
document.addEventListener("keydown", (e) => {
  modifierDown = e.metaKey || e.ctrlKey
  if (modifierDown && dot) void showPeek(dot)
})
document.addEventListener("keyup", (e) => (modifierDown = e.metaKey || e.ctrlKey))

// A page load (or back/forward) selects the page in the URL; the site root is a copy
// of Home (builder._use_home_as_landing_page), so it selects the Home dot.
document.addEventListener("nav", () => {
  const slug = simplifySlug(getFullSlug(window))
  void selectNote(slug === "/" ? ("Home" as SimpleSlug) : slug)
})

// Not while typing, e.g. in Quartz's search box, whose own Esc closes it.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return
  const target = e.target as HTMLElement | null
  if (target?.closest?.("input, textarea, [contenteditable]")) return
  if (zoomed) unzoom() // a zoomed picture goes first, the note stays
  else if (peeked) hidePeek()
  else closeNote()
})
