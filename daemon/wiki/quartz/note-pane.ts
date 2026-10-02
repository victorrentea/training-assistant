// The wiki is its graph: the full graph fills the left two thirds of the window for
// good, and this pane, the right third, shows the selected note (Home at start).
// Clicking a dot, or a link inside the note, selects that note: its dot turns
// purple and the pane swaps in place, without ever leaving the graph. Hovering a
// link in the note lights up its dot and the edge to it from the selected note.
// Every note shown here counts as seen on this browser: its dot and the links to it
// dim, so what is left to read stands out.
// Esc, or a second click on the selected dot, closes the note and deselects the dot:
// the pane goes away and the graph takes the whole window, re-fitted to it. The next
// click on a dot opens a note again, and the graph steps back to its two thirds.
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

// A click on a picture in the note (a slide, a screenshot) shows it fullscreen, to
// read its details, until Esc or a click on it. Real fullscreen when the browser
// grants it (the participant page's iframe allows it); otherwise, e.g. inside an
// iframe that doesn't, the overlay alone covers the window.
let zoomed: HTMLElement | null = null

function zoomImage(img: HTMLImageElement) {
  unzoom()
  const overlay = document.createElement("div")
  overlay.className = "note-pane-zoom"
  overlay.appendChild(Object.assign(document.createElement("img"), { src: img.currentSrc || img.src, alt: img.alt }))
  overlay.addEventListener("click", unzoom)
  document.body.appendChild(overlay)
  zoomed = overlay
  overlay.requestFullscreen?.().catch(() => {})
}

function unzoom() {
  if (!zoomed) return
  const overlay = zoomed
  zoomed = null
  if (document.fullscreenElement === overlay) void document.exitFullscreen().catch(() => {})
  overlay.remove()
}

// In real fullscreen the browser takes Esc for itself and never passes it on: leaving
// fullscreen is the only sign of it.
document.addEventListener("fullscreenchange", () => {
  if (zoomed && document.fullscreenElement !== zoomed) unzoom()
})

function paragraph(text: string) {
  return Object.assign(document.createElement("p"), { textContent: text })
}

// The class sits on <html>, so custom.scss can widen the graph and hide the pane at
// once. The graph re-fits on a window resize (patch-graph.py), so one is faked.
const isClosed = () => document.documentElement.classList.contains("note-closed")

function setClosed(closed: boolean) {
  if (closed === isClosed()) return
  document.documentElement.classList.toggle("note-closed", closed)
  window.dispatchEvent(new Event("resize"))
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
  body.scrollTop = 0
  if (!elts || elts.length === 0) {
    title.textContent = ""
    body.replaceChildren(paragraph("Could not load this note."))
    return
  }
  const note = elts.map((e) => e.cloneNode(true) as HTMLElement)
  // The note's own H1 moves up into the pane's head, which stays put while the body scrolls.
  const h1 = note.map((e) => (e.tagName === "H1" ? e : e.querySelector("h1"))).find(Boolean)
  title.innerHTML = h1?.innerHTML ?? ""
  h1?.remove()
  body.replaceChildren(...note.filter((e) => e !== h1))
  body.querySelectorAll<HTMLAnchorElement>("a[data-slug]").forEach((a) => {
    a.classList.toggle("seen", isSeen(simplifySlug(a.dataset.slug as never)))
  })
}

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
  else closeNote()
})
