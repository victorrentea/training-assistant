// Shift-peek for graph nodes: hover a dot and a chip at the cursor offers
// "Hold ⇧ Shift for details"; while Shift is held the note itself appears in a
// panel next to the node, and releasing Shift hides it again. The trainer can
// read a note without leaving the graph (click, read, back, repeat).
//
// Copied next to graph.inline.ts by daemon/wiki/builder.py; patch-graph.py makes
// the graph's hover handler call graphPreviewHover().
import { normalizeRelativeURLs } from "../../util/path"

const parser = new DOMParser()
const cache = new Map<string, Promise<HTMLElement[]>>()

let hovered: URL | null = null
let shiftDown = false
let mouseX = 0
let mouseY = 0
let chip: HTMLElement | null = null
let panel: HTMLElement | null = null

function element(className: string): HTMLElement {
  const el = document.createElement("div")
  el.className = className
  document.body.appendChild(el)
  return el
}

// The same content Quartz's own link popovers show: every `.popover-hint` of the page.
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
        // Only the note: the breadcrumbs, Quartz's title (the note opens with its own H1)
        // and the date line are page chrome.
        html.querySelectorAll(".breadcrumb-container, .article-title, .content-meta").forEach((el) => el.remove())
        return [...html.getElementsByClassName("popover-hint")] as HTMLElement[]
      })
    note.catch(() => cache.delete(key))
    cache.set(key, note)
  }
  return note
}

function placeChip() {
  if (!chip) return
  // Above-right of the cursor: graph labels hang under their node.
  chip.style.transform = `translate(${mouseX + 14}px, ${mouseY - 30}px)`
}

// About a quarter of the graph: 40% of its width, up to 60% of its height.
// The open global graph is the reference; the small sidebar graph uses the window.
function placePanel(p: HTMLElement) {
  const graph = document
    .elementFromPoint(mouseX, mouseY)
    ?.closest(".global-graph-container") as HTMLElement | null
  const box = graph?.getBoundingClientRect() ?? new DOMRect(0, 0, innerWidth, innerHeight)
  const width = Math.min(Math.max(box.width * 0.4, 320), 720, innerWidth - 32)
  const maxHeight = Math.max(box.height * 0.6, 240)
  p.style.width = `${width}px`
  p.style.maxHeight = `${maxHeight}px`

  const gap = 18
  const fitsRight = mouseX + gap + width <= innerWidth - 16
  const left = fitsRight ? mouseX + gap : Math.max(16, mouseX - gap - width)
  const height = Math.min(p.scrollHeight, maxHeight)
  const top = Math.min(Math.max(16, mouseY - height / 2), Math.max(16, innerHeight - height - 16))
  p.style.transform = `translate(${left}px, ${top}px)`
}

async function showPanel(url: URL) {
  const elts = await loadNote(url).catch(() => null)
  // Shift released or the mouse moved to another node while the page was loading.
  if (!elts || !shiftDown || hovered?.toString() !== url.toString()) return
  panel ??= element("graph-peek")
  panel.replaceChildren(...elts.map((e) => e.cloneNode(true)))
  panel.scrollTop = 0
  panel.classList.add("visible")
  placePanel(panel)
  panel.classList.toggle("clipped", panel.scrollHeight > panel.clientHeight)
}

function render() {
  if (hovered && !shiftDown) {
    chip ??= element("graph-peek-chip")
    chip.textContent = "Hold ⇧ Shift for details"
    chip.classList.add("visible")
    placeChip()
  } else {
    chip?.classList.remove("visible")
  }

  if (hovered && shiftDown) {
    showPanel(hovered)
  } else {
    panel?.classList.remove("visible")
  }
}

function setShift(down: boolean) {
  if (down === shiftDown) return
  shiftDown = down
  render()
}

export function graphPreviewHover(url: URL | null) {
  hovered = url
  if (url) loadNote(url) // warm up, so Shift shows the note instantly
  render()
}

// Pointer events carry the modifier state even when the wiki iframe has no
// keyboard focus, so moving the mouse with Shift held works too.
window.addEventListener("pointermove", (e) => {
  mouseX = e.clientX
  mouseY = e.clientY
  if (hovered && !shiftDown) placeChip()
  setShift(e.shiftKey)
})
window.addEventListener("keydown", (e) => e.key === "Shift" && setShift(true))
window.addEventListener("keyup", (e) => e.key === "Shift" && setShift(false))
window.addEventListener("blur", () => setShift(false))
document.addEventListener("nav", () => graphPreviewHover(null))
