// The wiki is its graph: the full graph fills the left two thirds of the window for
// good, and this pane, the right third, shows the selected note (Home at start).
// Clicking a dot, or a link inside the note, selects that note: its dot turns
// purple and the pane swaps in place, without ever leaving the graph. Hovering a
// link in the note lights up its dot and the edge to it from the selected note.
//
// Copied next to graph.inline.ts by daemon/wiki/builder.py; patch-graph.py makes the
// full graph register here (connectGraph) and call selectNote() on a click.
import { SimpleSlug, getFullSlug, normalizeRelativeURLs, resolveRelative, simplifySlug } from "../../util/path"

export type PaneGraph = {
  select(slug: SimpleSlug): void
  highlight(slug: SimpleSlug | null): void
}

const parser = new DOMParser()
const cache = new Map<string, Promise<HTMLElement[]>>()

let graph: PaneGraph | null = null
let selected: SimpleSlug | null = null
let highlighted: SimpleSlug | null = null
let pane: HTMLElement | null = null

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
    if (!slug) return
    e.preventDefault()
    e.stopPropagation()
    selectNote(slug)
  })
  body.addEventListener("mouseover", (e) => highlight(linkSlug(e.target)))
  body.addEventListener("mouseleave", () => highlight(null))
  document.body.appendChild(pane)
  return pane
}

function paragraph(text: string) {
  return Object.assign(document.createElement("p"), { textContent: text })
}

export async function selectNote(slug: SimpleSlug) {
  selected = slug
  highlight(null)
  graph?.select(slug)

  const pane = ensurePane()
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
}

// A page load (or back/forward) selects the page in the URL; the site root is a copy
// of Home (builder._use_home_as_landing_page), so it selects the Home dot.
document.addEventListener("nav", () => {
  const slug = simplifySlug(getFullSlug(window))
  void selectNote(slug === "/" ? ("Home" as SimpleSlug) : slug)
})
