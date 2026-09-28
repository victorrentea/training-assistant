// Node preview for the wiki graph: clicking a dot opens its note in a modal over
// the graph (about half of it), with a link to the full page; ⌘/Ctrl-click still
// navigates straight to the page. Hovering a dot shows a chip explaining both.
// The trainer can read notes without leaving the graph (click, read, back, repeat).
//
// Copied next to graph.inline.ts by daemon/wiki/builder.py; patch-graph.py makes
// the graph call graphPreviewHover() on hover and graphPreviewOpen() on click.
import { normalizeRelativeURLs } from "../../util/path"

const parser = new DOMParser()
const cache = new Map<string, Promise<HTMLElement[]>>()

let mouseX = 0
let mouseY = 0
let chip: HTMLElement | null = null
let backdrop: HTMLElement | null = null
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
  if (url && !opened) {
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

// Half the graph's surface (70% × 70%), centred on it: the open global graph is
// the reference, the small sidebar graph uses the window.
function placeDialog(dialog: HTMLElement) {
  const graph = document.querySelector(".global-graph-outer.active .global-graph-container")
  const box = graph?.getBoundingClientRect() ?? new DOMRect(0, 0, innerWidth, innerHeight)
  const width = Math.min(Math.max(box.width * 0.7, 320), innerWidth - 32)
  const height = Math.min(Math.max(box.height * 0.7, 240), innerHeight - 32)
  Object.assign(dialog.style, {
    width: `${width}px`,
    height: `${height}px`,
    left: `${box.left + (box.width - width) / 2}px`,
    top: `${box.top + (box.height - height) / 2}px`,
  })
}

export async function graphPreviewOpen(url: URL) {
  opened = url
  chip?.classList.remove("visible")

  if (!backdrop) {
    backdrop = document.createElement("div")
    backdrop.className = "graph-peek-backdrop"
    backdrop.innerHTML = `
      <div class="graph-peek" role="dialog" aria-modal="true">
        <div class="graph-peek-bar">
          <a class="graph-peek-open">Open full page ↗</a>
          <button class="graph-peek-close" aria-label="Close">✕</button>
        </div>
        <div class="graph-peek-body"></div>
      </div>`
    // A click outside the dialog closes it, like Quartz's own overlays.
    backdrop.addEventListener("click", (e) => e.target === backdrop && graphPreviewClose())
    backdrop.querySelector(".graph-peek-close")!.addEventListener("click", graphPreviewClose)
    document.body.appendChild(backdrop)
  }

  const dialog = backdrop.querySelector(".graph-peek") as HTMLElement
  const body = backdrop.querySelector(".graph-peek-body") as HTMLElement
  ;(backdrop.querySelector(".graph-peek-open") as HTMLAnchorElement).href = url.toString()
  body.replaceChildren(Object.assign(document.createElement("p"), { textContent: "Loading…" }))
  body.scrollTop = 0
  placeDialog(dialog)
  backdrop.classList.add("visible")

  const elts = await loadNote(url).catch(() => null)
  if (opened?.toString() !== url.toString()) return // closed, or another node opened meanwhile
  if (!elts || elts.length === 0) {
    body.replaceChildren(Object.assign(document.createElement("p"), { textContent: "Could not load this note." }))
    return
  }
  body.replaceChildren(...elts.map((e) => e.cloneNode(true)))
}

function graphPreviewClose() {
  opened = null
  backdrop?.classList.remove("visible")
}

window.addEventListener("pointermove", (e) => {
  mouseX = e.clientX
  mouseY = e.clientY
  placeChip()
})
// Capture phase, so Esc closes only the modal and not the global graph behind it too.
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
// Following a link (the full-page link or one inside the note) leaves the modal behind.
document.addEventListener("nav", () => {
  graphPreviewClose()
  graphPreviewHover(null)
})
