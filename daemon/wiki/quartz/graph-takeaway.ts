// Key takeaways: the trainer stars the notes his participants must leave with, and on
// every graph their dots get a filled star and a golden starburst behind them, live
// (Victor, 2026-10-19). Unrelated to the teal topic glow (graph-glow.ts): that one comes
// from an LLM score at build time, this one from a click of the trainer, during the day.
//
// The star sits on the dot's left, mid-height: the top corners hold the link count and
// the picture badges (graph-badges.ts), the label hangs below. On the trainer's machine
// every dot has one, hollow until he clicks it; everywhere else only the starred dots
// show theirs, filled, and nothing there is clickable.
//
// note-pane.ts keeps the starred set and the toggle; builder.py copies this file next
// to graph.inline.ts, and patch-graph.py makes one TakeawayMark per dot, puts its star
// and its burst in containers of their own and places them in its animation loop.
import { Sprite, Text, Texture } from "pixi.js"

export type TakeawayColors = {
  on: string // the filled star and the burst
  off: string // the hollow star the trainer clicks
  halo: string // the page background, behind the star so edges don't run through it
  font: string
}

const STAR_FONT = 11
// U+FE0E: the text glyphs, not emoji, so they take the theme's colours.
const FILLED = "★︎"
const HOLLOW = "☆︎"

// Drawn once, white, tinted per theme: a soft round core and eight rays, four long and
// four short - a star's sparkle, where the topic glow is a plain round haze.
let texture: Texture | null = null
const TEXTURE_SIZE = 256

function burstTexture(): Texture {
  if (texture) return texture
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = TEXTURE_SIZE
  const ctx = canvas.getContext("2d")!
  const c = TEXTURE_SIZE / 2
  const core = ctx.createRadialGradient(c, c, 0, c, c, c * 0.55)
  core.addColorStop(0, "rgba(255,255,255,1)")
  core.addColorStop(0.35, "rgba(255,255,255,0.75)")
  core.addColorStop(0.7, "rgba(255,255,255,0.25)")
  core.addColorStop(1, "rgba(255,255,255,0)")
  ctx.fillStyle = core
  ctx.fillRect(0, 0, TEXTURE_SIZE, TEXTURE_SIZE)
  for (let i = 0; i < 8; i++) {
    const long = i % 2 === 0
    const len = c * (long ? 0.98 : 0.62)
    const half = c * (long ? 0.085 : 0.06)
    ctx.save()
    ctx.translate(c, c)
    ctx.rotate((i * Math.PI) / 4)
    const ray = ctx.createLinearGradient(0, 0, len, 0)
    ray.addColorStop(0, "rgba(255,255,255,0.95)")
    ray.addColorStop(0.5, "rgba(255,255,255,0.45)")
    ray.addColorStop(1, "rgba(255,255,255,0)")
    ctx.fillStyle = ray
    ctx.beginPath()
    ctx.moveTo(0, -half)
    ctx.lineTo(len, 0)
    ctx.lineTo(0, half)
    ctx.closePath()
    ctx.fill()
    ctx.restore()
  }
  texture = Texture.from(canvas)
  return texture
}

export class TakeawayMark {
  readonly star: Text
  readonly burst: Sprite
  private starred = false

  // clickable: the trainer's machine. onToggle gets what the star should become.
  constructor(
    r: number,
    private colors: TakeawayColors,
    clickable: boolean,
    onToggle: (starred: boolean) => void,
  ) {
    this.burst = new Sprite({
      texture: burstTexture(),
      anchor: 0.5,
      eventMode: "none",
      tint: colors.on,
      visible: false,
    })
    this.burst.width = this.burst.height = 2 * r * 6.5
    this.star = new Text({
      text: HOLLOW,
      anchor: { x: 1, y: 0.5 },
      eventMode: clickable ? "static" : "none",
      cursor: clickable ? "pointer" : "default",
      visible: clickable,
      style: {
        fontSize: STAR_FONT,
        fill: colors.off,
        fontFamily: colors.font,
        stroke: { color: colors.halo, width: 3, join: "round" },
      },
      resolution: window.devicePixelRatio * 4,
    })
    if (clickable) {
      this.star.on("pointertap", (e) => {
        e.stopPropagation()
        onToggle(!this.starred)
      })
    }
  }

  set(starred: boolean, clickable: boolean) {
    if (starred === this.starred) return
    this.starred = starred
    this.burst.visible = starred
    this.star.text = starred ? FILLED : HOLLOW
    this.star.style.fill = starred ? this.colors.on : this.colors.off
    this.star.visible = starred || clickable
  }

  // The dot is at (x, y) with radius r. The burst turns slowly, so it reads as alive
  // without pulsing like the yellow Follow ring.
  place(x: number, y: number, r: number, time: number) {
    this.star.position.set(x - r - 2.5, y + 1.5)
    if (this.starred) {
      this.burst.position.set(x, y)
      this.burst.rotation = time / 6000
    }
  }
}
