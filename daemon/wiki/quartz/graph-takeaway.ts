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
// group with the same gold starburst; the label turns yellow too, like a star,
// outlined in black to stay readable over the burst (Victor, 2026-10-21); the dot is
// gold once read, white while unread (2026-10-23). In the participant page's Wiki tab every dot has a star to click,
// filled once it's theirs; elsewhere it shows, filled, once anyone starred the note,
// the trainer included. The trainer's star is his takeaway.
//
// Five levels of shine, climbing as stars pile up on the same note (his takeaway counts
// as one star): 1 a smaller, fainter starburst, 2 the takeaway's starburst as it was
// with a brighter star over it, and 3 to 5 add a soft glow under it that spreads wider
// each level (Victor, 2026-10-23 - level 1 was the full burst, too close to level 2).
// Its edges stay plain grey lines: drawn as gold rays out of the star (2026-10-19),
// they cluttered the picture and hid the graph's shape (Victor, 2026-10-23).
//
// note-pane.ts keeps the starred sets, the counts and the toggles; builder.py copies
// this file next to graph.inline.ts, and patch-graph.py makes one TakeawayMark per dot,
// puts its star and its burst in containers of their own and places them in its
// animation loop.
import { namedAfterAWhile } from "./graph-badges"
import { CanvasTextMetrics, Graphics, Rectangle, Sprite, Text, TextStyle, Texture, fontStringFromTextStyle } from "pixi.js"

export type TakeawayColors = {
  on: string // a star lit
  burst: string // the burst and the glow under it
  off: string // the hollow star the trainer clicks
  halo: string // the page background, behind the star so edges don't run through it
  font: string
}

// The size the star is drawn at; place() scales it to the label's font.
const STAR_FONT = 10
const STAR_STROKE = 3 // its dark halo, half of it each side of the glyph
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
// Under a hovered dot, under any burst: a soft glow in the text colour (white on dark),
// so a hover shows even when none of the dot's edges light up (Victor, 2026-10-23).
export function hoverGlow(color: string): Sprite {
  return new Sprite({ texture: hazeTexture(), anchor: 0.5, eventMode: "none", tint: color, alpha: 0.3, visible: false, zIndex: 1.3 })
}

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
  private hovered = false // the pointer on the star
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
      new Sprite({ texture, anchor: 0.5, eventMode: "none", tint: colors.burst, visible: false })
    this.burst = sprite(burstTexture())
    this.burst.width = this.burst.height = this.size
    this.flare = sprite(burstTexture())
    this.glow = sprite(hazeTexture())
    this.star = new Text({
      text: HOLLOW,
      anchor: { x: 0, y: 0 },
      eventMode: "none",
      cursor: "pointer",
      visible: false,
      style: {
        fontSize: STAR_FONT,
        fill: colors.off,
        fontFamily: colors.font,
        stroke: { color: colors.halo, width: STAR_STROKE, join: "round" },
      },
      resolution: window.devicePixelRatio * 4,
    })
    this.star.on("pointertap", (e) => {
      e.stopPropagation()
      onToggle(this.mode === "voter" ? !this.shine.mine : !this.shine.takeaway)
    })
    // Under the pointer an empty star fills, gold: a preview of the click, which then
    // keeps it filled (Victor, 2026-10-23).
    this.star.on("pointerover", () => {
      this.hovered = true
      this.set(this.shine)
    })
    namedAfterAWhile(this.star, "Favorite")
    this.star.on("pointerout", () => {
      this.hovered = false
      this.set(this.shine)
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
    const lit = own || (this.hovered && clickable)
    this.star.text = lit ? FILLED : HOLLOW
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
    this.star.style.fill = lit || total > 0 ? this.colors.on : this.colors.off
  }

  // Whether its star is drawn, and what it reads: for a test, the canvas has no DOM.
  get starShown(): boolean {
    return this.star.visible
  }

  get starText(): string {
    return this.star.visible ? this.star.text.replace(/\uFE0E/g, "") : ""
  }

  // The dot is at (x, y); its star's glyph starts at x + dx, sitting on the label's
  // baseline at y + baseline, drawn at font size `size`, so it reads as one more letter
  // of the name (Victor, 2026-10-23). The burst turns slowly, so it reads as alive
  // without pulsing like the yellow Follow ring.
  place(x: number, y: number, dx: number, baseline: number, size: number, time: number) {
    const scale = size / STAR_FONT
    this.star.scale.set(scale)
    this.star.position.set(
      x + dx - (STAR_STROKE / 2) * scale,
      y + baseline - baselineOf(this.star.style, STAR_STROKE) * scale,
    )
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

// How far below a text's top its baseline is, in its own units: Pixi draws the first
// line half the outline down, then the font's ascent (measureFont caches per font).
export function baselineOf(style: TextStyle, stroke: number): number {
  return stroke / 2 + CanvasTextMetrics.measureFont(fontStringFromTextStyle(style)).ascent
}

// A new star on a note arrives as a comet (Victor, 2026-10-23): it falls from above the
// window onto the dot in COMET_MS, its tail fading behind it, and the dot's burst grows
// to its new level only on impact, with a short flash. Drawn in graph units, like the
// dots: k is the zoom, to keep the comet's size on screen.
export const COMET_MS = 900
export const FLASH_MS = 450

export function drawComet(
  g: Graphics,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  p: number, // 0..1 of the flight
  k: number,
  gold: string,
) {
  const at = (q: number) => {
    const e = q * q // falling faster as it nears
    return [x0 + (x1 - x0) * e, y0 + (y1 - y0) * e]
  }
  const steps = 14
  const tail = 0.3 // of the flight, behind the head
  for (let i = 0; i < steps; i++) {
    const qa = Math.max(0, p - (tail * (i + 1)) / steps)
    const qb = Math.max(0, p - (tail * i) / steps)
    if (qb <= qa) continue
    const [ax, ay] = at(qa)
    const [bx, by] = at(qb)
    const fade = 1 - i / steps
    g.moveTo(ax, ay)
      .lineTo(bx, by)
      .stroke({ color: gold, alpha: 0.9 * fade, width: ((3.2 * fade + 0.4) / k), cap: "round" })
  }
  const [hx, hy] = at(p)
  g.circle(hx, hy, 3.4 / k).fill({ color: gold, alpha: 0.5 })
  g.circle(hx, hy, 1.8 / k).fill({ color: 0xffffff, alpha: 1 })
}

// The flash where a comet lands: a ring of light widening and fading out, q 0..1.
export function drawFlash(g: Graphics, x: number, y: number, r: number, q: number, gold: string) {
  g.circle(x, y, r * (1.5 + 4 * q)).fill({ color: gold, alpha: 0.45 * (1 - q) })
  g.circle(x, y, r * (1 + 2 * q)).fill({ color: 0xffffff, alpha: 0.6 * (1 - q) })
}

// The trainer's next star (Victor, 2026-11-05): while he walks the room through what
// it starred, the graph shows him where to go next - the unread notes with the most
// stars, a takeaway counting as one. Any of them on screen: four triangles turn slowly
// around each. None: a double chevron at the window's edge points at the nearest. Only
// on his machine, and never a note he has read, so the cue moves on as he opens them.
export type StarCue =
  | { kind: "none" }
  | { kind: "aim"; ids: string[] }
  | { kind: "arrow"; id: string; x: number; y: number; angle: number }

type CueDot = { id: string; stars: number; x: number; y: number } // x, y: on screen

const ARROW_INSET = 64 // from the window's edge, clear of the pills along it
const IN_VIEW_MARGIN = 20 // a dot this close to the edge is half gone: it counts as out

export function nextStarCue(dots: CueDot[], width: number, height: number): StarCue {
  const most = Math.max(0, ...dots.map((d) => d.stars))
  if (most === 0) return { kind: "none" }
  const next = dots.filter((d) => d.stars === most)
  const inside = (at: number, size: number) => at >= IN_VIEW_MARGIN && at <= size - IN_VIEW_MARGIN
  const inView = next.filter((d) => inside(d.x, width) && inside(d.y, height))
  if (inView.length > 0) return { kind: "aim", ids: inView.map((d) => d.id) }
  const cx = width / 2
  const cy = height / 2
  const nearest = next.reduce((a, b) => (Math.hypot(b.x - cx, b.y - cy) < Math.hypot(a.x - cx, a.y - cy) ? b : a))
  const dx = nearest.x - cx
  const dy = nearest.y - cy
  // Where the line from the window's centre to the dot meets the inset edge.
  const reach = Math.min(
    dx === 0 ? Infinity : (cx - ARROW_INSET) / Math.abs(dx),
    dy === 0 ? Infinity : (cy - ARROW_INSET) / Math.abs(dy),
  )
  return { kind: "arrow", id: nearest.id, x: cx + dx * reach, y: cy + dy * reach, angle: Math.atan2(dy, dx) }
}

const AIM_TURN_MS = 15_000 // a full turn
const AIM_GAP = 20 // from the dot's rim to a triangle's tip, on screen
// Longer than wide: an equilateral one has no direction once it has turned, and the
// four read as a pinwheel instead of pointing at the dot.
const AIM_LENGTH = 24 // a triangle, tip to base
const AIM_HALF_BASE = 8

// Four triangles pointing at the dot at (x, y) (in graph units, like its radius r),
// the same size on screen at any zoom (k); gold like the arrow, a thin black outline
// keeps them apart from the burst behind them.
export function drawAim(g: Graphics, x: number, y: number, r: number, k: number, time: number, color: string) {
  const tip = r + AIM_GAP / k
  const base = tip + AIM_LENGTH / k
  const half = AIM_HALF_BASE / k
  const turn = (time / AIM_TURN_MS) * 2 * Math.PI
  for (let i = 0; i < 4; i++) {
    const a = turn + (i * Math.PI) / 2
    const cos = Math.cos(a)
    const sin = Math.sin(a)
    g.poly([
      x + cos * tip, y + sin * tip,
      x + cos * base - sin * half, y + sin * base + cos * half,
      x + cos * base + sin * half, y + sin * base - cos * half,
    ])
      .fill({ color })
      .stroke({ color: "#000000", width: 0.75 / k, join: "round" })
  }
}

const CHEVRON_ARM = 20 // a chevron, tip to the end of an arm, along the line it points
const CHEVRON_HALF = 24 // and across it
const CHEVRON_GAP = 18 // from one chevron's tip to the next
const CHEVRON_NUDGE = 6 // how far the pair drifts towards the note, and back
const CHEVRON_WIDTH = 6

// A double chevron at (x, y) in graph units, pointing along angle, drifting that way
// and back. Black under gold, the way the labels are outlined.
export function drawChevrons(g: Graphics, x: number, y: number, angle: number, k: number, time: number, gold: string) {
  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  const nudge = (CHEVRON_NUDGE * (1 + Math.sin(time / 350))) / 2
  // (along, across) from the pair's centre, on screen, to graph units.
  const at = (along: number, across: number): [number, number] => [
    x + (cos * (along + nudge) - sin * across) / k,
    y + (sin * (along + nudge) + cos * across) / k,
  ]
  for (const [width, color] of [[CHEVRON_WIDTH + 3, "#000000"], [CHEVRON_WIDTH, gold]] as const) {
    for (const tip of [CHEVRON_GAP / 2, -CHEVRON_GAP / 2]) {
      g.moveTo(...at(tip - CHEVRON_ARM, -CHEVRON_HALF))
        .lineTo(...at(tip, 0))
        .lineTo(...at(tip - CHEVRON_ARM, CHEVRON_HALF))
        .stroke({ color, width: width / k, cap: "round", join: "round" })
    }
  }
}
