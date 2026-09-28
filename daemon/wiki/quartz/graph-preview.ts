// Node preview for the wiki graph: clicking a dot zooms its note out of that dot
// into a modal centred on the graph (about half of it), with a link to the full
// page; closing zooms it back into the dot. ⌘/Ctrl-click still navigates straight
// to the page. Hovering a dot shows a chip explaining both clicks. (The dot itself
// stays purple meanwhile: that part lives in graph.inline.ts, see patch-graph.py.)
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
let origin = { x: 0, y: 0 } // the clicked dot, where the modal grows from and shrinks back to
let running: Animation[] = []

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

// Zoom between the dot and the dialog: the dialog starts (or ends) shrunk onto the
// dot's position, the backdrop fades along. Skipped for prefers-reduced-motion.
function zoom(dialog: HTMLElement, opening: boolean): Promise<void> {
  running.forEach((a) => a.cancel())
  running = []
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return Promise.resolve()
  const r = dialog.getBoundingClientRect()
  const dx = origin.x - (r.left + r.width / 2)
  const dy = origin.y - (r.top + r.height / 2)
  const dot = { transform: `translate(${dx}px, ${dy}px) scale(0.02)`, opacity: 0.3 }
  const full = { transform: "none", opacity: 1 }
  const timing = opening
    ? { duration: 280, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" }
    : { duration: 220, easing: "cubic-bezier(0.6, 0, 0.8, 0.4)" }
  running = [
    dialog.animate(opening ? [dot, full] : [full, dot], timing),
    backdrop!.animate(opening ? [{ opacity: 0 }, { opacity: 1 }] : [{ opacity: 1 }, { opacity: 0 }], timing),
  ]
  return Promise.all(running.map((a) => a.finished)).then(
    () => {},
    () => {}, // cancelled by a newer open/close
  )
}

function paragraph(text: string) {
  return Object.assign(document.createElement("p"), { textContent: text })
}

export async function graphPreviewOpen(url: URL) {
  opened = url
  origin = { x: mouseX, y: mouseY }
  chip?.classList.remove("visible")

  if (!backdrop) {
    backdrop = document.createElement("div")
    backdrop.className = "graph-peek-backdrop"
    backdrop.innerHTML = `
      <div class="graph-peek" role="dialog" aria-modal="true">
        <div class="graph-peek-head">
          <h1 class="graph-peek-title"></h1>
          <a class="graph-peek-open">Open full page ↗</a>
          <button class="graph-peek-close" aria-label="Close">✕</button>
        </div>
        <div class="graph-peek-body"></div>
      </div>`
    // A click outside the dialog closes it, like Quartz's own overlays.
    backdrop.addEventListener("click", (e) => e.target === backdrop && graphPreviewClose())
    backdrop.querySelector(".graph-peek-close")!.addEventListener("click", () => graphPreviewClose())
    document.body.appendChild(backdrop)
  }

  const dialog = backdrop.querySelector(".graph-peek") as HTMLElement
  const title = backdrop.querySelector(".graph-peek-title") as HTMLElement
  const body = backdrop.querySelector(".graph-peek-body") as HTMLElement
  ;(backdrop.querySelector(".graph-peek-open") as HTMLAnchorElement).href = url.toString()
  title.textContent = ""
  body.replaceChildren(paragraph("Loading…"))
  body.scrollTop = 0
  placeDialog(dialog)
  backdrop.classList.add("visible")
  zoom(dialog, true)

  const elts = await loadNote(url).catch(() => null)
  if (opened?.toString() !== url.toString()) return // closed meanwhile
  if (!elts || elts.length === 0) {
    body.replaceChildren(paragraph("Could not load this note."))
    return
  }
  const note = elts.map((e) => e.cloneNode(true) as HTMLElement)
  // The note's own H1 moves up into the head row, next to the link and the ✕.
  const h1 = note.map((e) => (e.tagName === "H1" ? e : e.querySelector("h1"))).find(Boolean)
  if (h1) {
    title.innerHTML = h1.innerHTML
    h1.remove()
  }
  body.replaceChildren(...note.filter((e) => e !== h1))
}

async function graphPreviewClose(animate = true) {
  if (!opened || !backdrop) return
  opened = null
  if (animate) await zoom(backdrop.querySelector(".graph-peek") as HTMLElement, false)
  // Reopened while it was shrinking: leave the new one alone.
  if (!opened) backdrop.classList.remove("visible")
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
// Following a link (the full-page link or one inside the note) leaves the modal
// behind at once: the page is changing under it, no time for the zoom back.
document.addEventListener("nav", () => {
  graphPreviewClose(false)
  graphPreviewHover(null)
})
