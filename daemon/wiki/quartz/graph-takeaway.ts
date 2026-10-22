// Key takeaways: the trainer stars the notes his participants must leave with, and on
// every graph their dots get a filled star and a golden starburst behind them, live
// (Victor, 2026-10-19).
//
// On the trainer's machine every dot has a star he clicks, right after the note's name,
// with no count: the bigger burst says how many starred it, the popover gives the
// number (Victor, 2026-10-23 - it was "3☆" left of the dot, mid-height; for a moment
// it ended the badge column at the dot's top-right). Hollow until he stars the note, filled after; a click on it un-stars it
// right there, without opening the note (Victor, 2026-10-22).
//
// Participants star the notes they found interesting, and those shine for the whole
// group with the same gold starburst; the dot and its label turn yellow too, like a
// star, the label outlined in black to stay readable over the burst (Victor,
// 2026-10-21). In the participant page's Wiki tab every dot has a star to click,
// filled once it's theirs; elsewhere it shows, filled, once anyone starred the note,
// the trainer included. The trainer's star is his takeaway.
//
// Five levels of shine, climbing as stars pile up on the same note (his takeaway counts
// as one star): 1 a smaller, fainter starburst, 2 the takeaway's starburst as it was
// with a brighter star over it, and 3 to 5 add a soft glow under it that spreads wider
// each level (Victor, 2026-10-23 - level 1 was the full burst, too close to level 2). The rays along the edges
// stay the same at every level.
//
// note-pane.ts keeps the starred sets, the counts and the toggles; builder.py copies
// this file next to graph.inline.ts, and patch-graph.py makes one TakeawayMark per dot,
// puts its star and its burst in containers of their own and places them in its
// animation loop.
import { Color, Graphics, Rectangle, Sprite, Text, Texture } from "pixi.js"

export type TakeawayColors = {
  on: string // the burst
  off: string // the hollow star the trainer clicks
  halo: string // the page background, behind the star so edges don't run through it
  font: string
}

const STAR_FONT = 10
// Around the glyph, in graph units: the star alone is a fingertip's fraction on a phone.
const STAR_HIT_PAD = 5
// U+FE0E: the text glyph, not the emoji, so it takes the theme's colour.
const HOLLOW = "☆︎"
const FILLED = "★︎"

// Who is looking decides what the star by a dot does: the trainer stars key takeaways,
// a participant in the participant page stars what they found interesting, anyone
// else (the wiki in a tab of its own) only sees the counts.
export type StarMode = "trainer" | "voter" | "viewer"

// What a dot shows: whether the trainer starred it, how many participants did, whether
// this participant is one of them, and its level of shine (0: none, up to MAX_LEVEL).
export type DotShine = { takeaway: boolean; count: number; mine: boolean; level: number }

// The stars a note needs for each level, the trainer's takeaway counting as one: a
// level each for the first three, then a little harder to climb.
const LEVEL_AT = [1, 2, 3, 5, 8]
export const MAX_LEVEL = LEVEL_AT.length

export function shineLevel(takeaway: boolean, count: number): number {
  const stars = count + (takeaway ? 1 : 0)
  return LEVEL_AT.filter((at) => stars >= at).length
}

// Per level (index 0 = level 1): the burst's size (times the takeaway's) and alpha,
// whether a second, offset burst brightens it, and the glow under it (size times the
// dot's diameter, alpha; 0 for none).
const LEVELS = [
  { burst: 0.8, burstAlpha: 0.65, flare: false, glow: 0, glowAlpha: 0 },
  { burst: 1.2, burstAlpha: 1, flare: true, glow: 0, glowAlpha: 0 },
  { burst: 1.3, burstAlpha: 1, flare: true, glow: 9, glowAlpha: 0.3 },
  { burst: 1.4, burstAlpha: 1, flare: true, glow: 13, glowAlpha: 0.4 },
  { burst: 1.5, burstAlpha: 1, flare: true, glow: 17, glowAlpha: 0.5 },
]

// Drawn once, white, tinted per theme: a soft round core and eight rays, four long and
// four short - a star's sparkle.
let texture: Texture | null = null
let haze: Texture | null = null
const TEXTURE_SIZE = 256

// The glow under a shining note's burst from level 3: a plain round haze, white.
function hazeTexture(): Texture {
  if (haze) return haze
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = TEXTURE_SIZE
  const ctx = canvas.getContext("2d")!
  const c = TEXTURE_SIZE / 2
  const g = ctx.createRadialGradient(c, c, 0, c, c, c)
  g.addColorStop(0, "rgba(255,255,255,1)")
  g.addColorStop(0.4, "rgba(255,255,255,0.45)")
  g.addColorStop(1, "rgba(255,255,255,0)")
  ctx.fillStyle = g
  ctx.fillRect(0, 0, TEXTURE_SIZE, TEXTURE_SIZE)
  haze = Texture.from(canvas)
  return haze
}

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
  readonly flare: Sprite // a second burst over the first, from level 2: a brighter star
  readonly glow: Sprite // under the bursts, from level 3, wider each level
  private shine: DotShine = { takeaway: false, count: 0, mine: false, level: 0 }
  private readonly mode: StarMode
  private readonly colors: TakeawayColors
  private readonly size: number
  private readonly r: number

  // onToggle gets what the star should become: the takeaway for the trainer, the
  // participant's own star for a voter.
  constructor(r: number, colors: TakeawayColors, mode: StarMode, onToggle: (starred: boolean) => void) {
    this.mode = mode
    this.colors = colors
    this.size = 2 * r * 6.5
    this.r = r
    const sprite = (texture: Texture) =>
      new Sprite({ texture, anchor: 0.5, eventMode: "none", tint: colors.on, visible: false })
    this.burst = sprite(burstTexture())
    this.burst.width = this.burst.height = this.size
    this.flare = sprite(burstTexture())
    this.glow = sprite(hazeTexture())
    this.star = new Text({
      text: HOLLOW,
      anchor: { x: 0, y: 0.5 },
      eventMode: "none",
      cursor: "pointer",
      visible: false,
      style: {
        fontSize: STAR_FONT,
        fill: colors.off,
        fontFamily: colors.font,
        stroke: { color: colors.halo, width: 3, join: "round" },
      },
      resolution: window.devicePixelRatio * 4,
    })
    this.star.on("pointertap", (e) => {
      e.stopPropagation()
      onToggle(this.mode === "voter" ? !this.shine.mine : !this.shine.takeaway)
    })
    this.set(this.shine)
  }

  set(shine: DotShine) {
    this.shine = shine
    const { takeaway, count, mine, level } = shine
    const look = level > 0 ? LEVELS[Math.min(level, MAX_LEVEL) - 1] : null
    this.burst.visible = look !== null
    this.flare.visible = look?.flare ?? false
    this.glow.visible = (look?.glow ?? 0) > 0
    if (look) {
      this.burst.width = this.burst.height = this.size * look.burst
      this.burst.alpha = look.burstAlpha
      this.flare.width = this.flare.height = this.size * look.burst * 0.85
      this.flare.alpha = 0.85
      this.glow.width = this.glow.height = 2 * this.r * look.glow
      this.glow.alpha = look.glowAlpha
    }
    // Everyone's stars, his takeaway counting as one, as for the level of shine.
    const total = count + (takeaway ? 1 : 0)
    // Filled when it's the reader's own: the trainer's takeaway, the participant's star.
    const own = this.mode === "trainer" ? takeaway : this.mode === "voter" ? mine : total > 0
    const clickable = this.mode !== "viewer"
    const visible = clickable || total > 0
    this.star.text = own ? FILLED : HOLLOW
    const b = this.star.getLocalBounds()
    this.star.hitArea = new Rectangle(
      b.x - STAR_HIT_PAD,
      b.y - STAR_HIT_PAD,
      b.width + 2 * STAR_HIT_PAD,
      b.height + 2 * STAR_HIT_PAD,
    )
    this.star.visible = visible
    this.star.eventMode = clickable ? "static" : "none"
    this.star.cursor = clickable ? "pointer" : "default"
    this.star.style.fill = own || total > 0 ? this.colors.on : this.colors.off
  }

  // Whether its star is drawn, and what it reads: for a test, the canvas has no DOM.
  get starShown(): boolean {
    return this.star.visible
  }

  get starText(): string {
    return this.star.visible ? this.star.text.replace(/\uFE0E/g, "") : ""
  }

  // The dot is at (x, y); its star's left edge, mid-height, at (x + dx, y + dy), after
  // the label. The burst turns slowly, so it reads as alive
  // without pulsing like the yellow Follow ring.
  place(x: number, y: number, dx: number, dy: number, time: number) {
    this.star.position.set(x + dx, y + dy)
    if (this.shine.level > 0) {
      this.burst.position.set(x, y)
      this.burst.rotation = time / 6000
      // Turned the other way and offset half a ray: the two together sparkle more.
      this.flare.position.set(x, y)
      this.flare.rotation = Math.PI / 8 - time / 9000
      this.glow.position.set(x, y)
    }
  }
}

// An edge touching a starred dot is a ray of light out of its star (Victor, 2026-10-19):
// gold and bright at the starred end, fading into the plain grey edge at the other end;
// between two starred dots, gold at both ends and grey midway. Drawn as short segments
// of stepped colour: a FillGradient per edge per frame would build a texture each time.
const RAY_STEPS = 16

// Any CSS colour the theme gives (#hex, rgb(...)), as 0-255 channels.
function rgb(css: string): number[] {
  return [...new Color(css.trim()).toUint8RgbArray()].slice(0, 3)
}

export function drawRay(
  g: Graphics,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  goldAt0: boolean,
  goldAt1: boolean,
  gold: string,
  grey: string,
  width: number, // the plain edge's width, already divided by the zoom
  alpha: number, // the plain edge's alpha
) {
  const a = rgb(gold)
  const b = rgb(grey)
  for (let i = 0; i < RAY_STEPS; i++) {
    const t0 = i / RAY_STEPS
    const t1 = (i + 1) / RAY_STEPS
    const mid = (t0 + t1) / 2
    // 1 at a gold end, 0 where the edge is plain grey.
    const glow = Math.max(goldAt0 ? 1 - mid / (goldAt1 ? 0.5 : 1) : 0, goldAt1 ? 1 - (1 - mid) / (goldAt0 ? 0.5 : 1) : 0, 0)
    const w = glow * glow * (3 - 2 * glow) // smoothstep: the gold holds near the star, then fades
    const c = a.map((v, j) => Math.round(b[j] + (v - b[j]) * w))
    g.moveTo(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0)
      .lineTo(x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)
      .stroke({
        color: (c[0] << 16) | (c[1] << 8) | c[2],
        alpha: alpha + (0.95 - alpha) * w,
        width: width * (1 + 1.6 * w),
      })
  }
}
