// Node preview for the wiki graph: clicking a dot docks its note in a panel over
// half of the graph, on the side away from that dot, with a link to the full page;
// ⌘/Ctrl-click still navigates straight to the page. The rest of the graph stays
// visible and clickable, so clicking another dot just swaps the panel's note.
// Hovering a dot shows a chip explaining both clicks.
//
// Copied next to graph.inline.ts by daemon/wiki/builder.py; patch-graph.py makes
// the graph call graphPreviewHover() on hover and graphPreviewOpen() on click.
import { normalizeRelativeURLs } from "../../util/path"

const parser = new DOMParser()
const cache = new Map<string, Promise<HTMLElement[]>>()

let mouseX = 0
let mouseY = 0
let chip: HTMLElement | null = null
let panel: HTMLElement | null = null
let opened: URL | null = null

// The same content Quartz's own link popovers show (every `.popover-hint` of the
// page), minus the page chrome: breadcrumbs, Quartz's title (the note opens with
// its own H1) and the date line.
function loadNote(url: URL): Promise<HTMLElement[]> {
  const key = url.toString()
  let note = cache.get(key)
  if (!note) {
    note = fetch(key)
      .then((res) => res.text())
      .then((text) => {
        const html = parser.parseFromString(text, "text/html")
        normalizeRelativeURLs(html, url)
        html.querySelectorAll("[id]").forEach((el) => (el.id = `graph-peek-${el.id}`))
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

export function graphPreviewHover(url: URL | null) {
  if (url) {
    loadNote(url) // warm up, so a click shows the note instantly
    if (!chip) {
      chip = document.createElement("div")
      chip.className = "graph-peek-chip"
      chip.textContent = "Click for details · ⌘/Ctrl-click opens the page"
      document.body.appendChild(chip)
    }
    chip.classList.add("visible")
    placeChip()
  } else {
    chip?.classList.remove("visible")
  }
}

function placeChip() {
  // Above-right of the cursor: graph labels hang under their node.
  if (chip) chip.style.transform = `translate(${mouseX + 14}px, ${mouseY - 30}px)`
}

// Half of the graph, full height, on the side away from the clicked dot so it stays
// in view. The open global graph is the reference; the small sidebar graph uses the
// window. The side is kept while the panel stays open, so browsing doesn't jump.
function placePanel(p: HTMLElement) {
  const graph = document.querySelector(".global-graph-outer.active .global-graph-container")
  const box = graph?.getBoundingClientRect() ?? new DOMRect(0, 0, innerWidth, innerHeight)
  const width = Math.max(box.width / 2, Math.min(320, innerWidth - 32))
  const onLeft = mouseX > box.left + box.width / 2
  Object.assign(p.style, {
    width: `${width}px`,
    height: `${box.height}px`,
    left: `${onLeft ? box.left : box.right - width}px`,
    top: `${box.top}px`,
  })
}

function paragraph(text: string) {
  return Object.assign(document.createElement("p"), { textContent: text })
}

export async function graphPreviewOpen(url: URL) {
  const wasOpen = opened !== null
  opened = url

  if (!panel) {
    panel = document.createElement("div")
    panel.className = "graph-peek"
    panel.setAttribute("role", "dialog")
    panel.innerHTML = `
      <div class="graph-peek-head">
        <h1 class="graph-peek-title"></h1>
        <a class="graph-peek-open">Open full page ↗</a>
        <button class="graph-peek-close" aria-label="Close">✕</button>
      </div>
      <div class="graph-peek-body"></div>`
    panel.querySelector(".graph-peek-close")!.addEventListener("click", graphPreviewClose)
    document.body.appendChild(panel)
  }

  const title = panel.querySelector(".graph-peek-title") as HTMLElement
  const body = panel.querySelector(".graph-peek-body") as HTMLElement
  ;(panel.querySelector(".graph-peek-open") as HTMLAnchorElement).href = url.toString()
  title.textContent = ""
  body.replaceChildren(paragraph("Loading…"))
  body.scrollTop = 0
  if (!wasOpen) placePanel(panel)
  panel.classList.add("visible")

  const elts = await loadNote(url).catch(() => null)
  if (opened?.toString() !== url.toString()) return // closed, or another dot clicked meanwhile
  if (!elts || elts.length === 0) {
    body.replaceChildren(paragraph("Could not load this note."))
    return
  }
  const note = elts.map((e) => e.cloneNode(true) as HTMLElement)
  // The note's own H1 moves up into the panel's head, next to the link and the ✕.
  const h1 = note.map((e) => (e.tagName === "H1" ? e : e.querySelector("h1"))).find(Boolean)
  if (h1) {
    title.innerHTML = h1.innerHTML
    h1.remove()
  }
  body.replaceChildren(...note.filter((e) => e !== h1))
}

function graphPreviewClose() {
  opened = null
  panel?.classList.remove("visible")
}

window.addEventListener("pointermove", (e) => {
  mouseX = e.clientX
  mouseY = e.clientY
  placeChip()
})
// Capture phase, so Esc closes only the panel and not the global graph behind it too.
window.addEventListener(
  "keydown",
  (e) => {
    if (opened && e.key.startsWith("Esc")) {
      e.preventDefault()
      e.stopPropagation()
      graphPreviewClose()
    }
  },
  true,
)
// Following a link (the full-page link or one inside the note) leaves the panel behind.
document.addEventListener("nav", () => {
  graphPreviewClose()
  graphPreviewHover(null)
})
