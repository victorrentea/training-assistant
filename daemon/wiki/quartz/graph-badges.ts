// Badges on the graph's dots, so a reader sees at a glance which notes are worth
// opening: a tiny picture left of the dot when the note shows a slide or a screenshot,
// above it a small grey link glyph (a box with an arrow leaving it) for the note's external links,
// with "×3" after it from two up, and right of it, at mid-height, one row for its
// emotional anchors: 🎬 for the shorts played in the room and ⚓ for the moments the
// summarizer tags, each with ×N from two up (both are the same thing: a moment that
// moved the room). Each has
// the labels' black outline, so it reads over the takeaway glow; none, no row (Victor,
// 2026-10-23 - it was a 🔗 emoji, before that 🌐, and ⚓ with a lowered count, ⚓₂, on a
// disc of the page background, which read as a black blob on the glow; repeated chains,
// 🔗🔗🔗🔗, read as a mess; before that "↗3"). A detail, not a key number: it was "🔗3"
// in bold, which drew the eye before the note titles (Victor, 2026-10-16).
//
// daemon/wiki/builder.py scans the built pages into note-badges.json at the site
// root and copies this file next to graph.inline.ts; patch-graph.py makes the graph
// load the JSON before it creates its dots, put one NoteBadge per badged dot in a
// container of its own (not the labels', which fades out when zoomed out) and place
// it in its animation loop.
import { Container, Graphics, Text } from "pixi.js"
import { FullSlug, SimpleSlug, pathToRoot, simplifySlug } from "../../util/path"

// No anchors or shorts: a site built before them.
type Badges = { img: boolean; links: number; anchors?: number; shorts?: number }

export type BadgeColors = {
  glyph: string // the drawn glyphs, picture frame and link: the ⚓ emoji's grey
  count: string // the "×3" after it
  font: string
}

const loaded = new Map<string, Promise<Map<SimpleSlug, Badges>>>()

// Fetched once per site. A site published before badges existed has no JSON: no badges.
export function loadBadges(fullSlug: FullSlug): Promise<Map<SimpleSlug, Badges>> {
  const url = new URL(`${pathToRoot(fullSlug)}/note-badges.json`, window.location.href).toString()
  let badges = loaded.get(url)
  if (!badges) {
    badges = fetch(url)
      .then((res) => (res.ok ? res.json() : {}))
      .catch(() => ({}))
      .then(
        (json: Record<string, Badges>) =>
          new Map(Object.entries(json).map(([k, v]) => [simplifySlug(k as FullSlug), v])),
      )
    loaded.set(url, badges)
  }
  return badges
}

// In graph units, like the dots and labels: the badges zoom with the stage. Held at a
// constant size on screen instead, they shrank next to their dot when zoomed in and
// looked detached from it.
const PICTURE_W = 10
const PICTURE_H = 8
const PICTURE_SCALE = 0.9
const EMOJI_FONT = 9

// Frame, mountain and sun: a picture, drawn rather than the 🖼️ emoji, which is
// mush at this size and can't take the theme's colours. Its frame in the ⚓'s grey,
// a green mountain and a yellow sun in it, so the pictures catch the
// eye in the crowd; the labels' black outline, like the link glyph; 0.9 of its first
// size (Victor, 2026-10-23 - it was all amber on a patch of the page background).
function picture(colors: BadgeColors): Graphics {
  const w = PICTURE_W
  const h = PICTURE_H
  const g = new Graphics({ eventMode: "none" })
  const shapes = (frame: string, mountain: string, sun: string, extra: number) =>
    g
      .roundRect(0, -h, w, h, 1.5)
      .stroke({ color: frame, width: 1.1 + extra, alignment: 0.5 })
      .poly([1, -1, 4.2, -5, 6.2, -3, 7.3, -4.1, w - 1, -1])
      .fill({ color: mountain })
      .stroke({ color: mountain, width: extra, join: "round" })
      .circle(7.3, -h + 2.4, 1 + extra / 2)
      .fill({ color: sun })
  shapes(OUTLINE, OUTLINE, OUTLINE, 1.6)
  g.beginPath()
  shapes(colors.glyph, "#22c55e", "#facc15", 0)
  g.scale.set(PICTURE_SCALE)
  return g
}

// Bottom-left corner at (0, 0): ⚓ per moment, then 🎬 per short.
// Bottom-left corner at (0, 0): 🎬 then ⚓, each once, with "×n" after it from two up,
// like the links' count (Victor, 2026-10-23 - ⚓⚓🎬, one emoji per item, ran long).
function anchors(moments: number, shorts: number, colors: BadgeColors): Container {
  const row = new Container({ eventMode: "passive" })
  let x = 0
  for (const [emoji, n, name] of [
    [SHORT, shorts, "Short"],
    [ANCHOR, moments, "Emotional anchor"],
  ] as const) {
    if (n === 0) continue
    const glyph = outlined(emojiText(emoji))
    namedAfterAWhile(glyph, name)
    glyph.x = x
    row.addChild(glyph)
    x += EMOJI_FONT + 0.6 // the emoji's picture is about 1em wide, its measured width more
    if (n > 1) {
      const count = countText(n, colors)
      count.position.set(x - 0.6, -EMOJI_FONT * 0.55)
      row.addChild(count)
      x += count.width + 0.6
    }
  }
  return row
}

// Bottom-left corner at (0, 0): the link glyph, then "×n" from two up.
function times(n: number, colors: BadgeColors): Container {
  const glyph = linkGlyph(colors)
  namedAfterAWhile(glyph, "Link")
  const row = new Container({ eventMode: "passive", children: [glyph] })
  if (n > 1) {
    const count = countText(n, colors)
    // Mid-height of the glyph's box, not of the whole glyph with its arrow.
    count.position.set(LINK_W - 0.4, -LINK_BOX / 2 + 0.6)
    row.addChild(count)
  }
  return row
}

// "×n", small and grey: a detail, it mustn't jump out. Left edge, mid-height at (0, 0).
function countText(n: number, colors: BadgeColors): Text {
  return new Text({
    eventMode: "none",
    text: `×${n}`,
    anchor: { x: 0, y: 0.5 },
    style: {
      fontSize: EMOJI_FONT * 0.8,
      fontWeight: "600",
      fill: colors.count,
      fontFamily: colors.font,
      stroke: { color: OUTLINE, width: 2.5, join: "round" },
    },
    resolution: window.devicePixelRatio * 4,
  })
}

// A box with an arrow leaving it by its open top-right corner: "goes out of the wiki",
// drawn rather than the 🔗 emoji, so it takes the ⚓'s grey and an
// outline, half an emoji's size (Victor, 2026-10-23). Bottom-left corner at (0, 0).
const LINK_W = 5
const LINK_BOX = (7.5 * LINK_W) / 9 // the box's side
function linkGlyph(colors: BadgeColors): Graphics {
  const g = new Graphics({ eventMode: "none" })
  const k = LINK_W / 9 // drawn on a 9-unit grid
  const draw = () =>
    g
      .moveTo(3.5 * k, -7.5 * k)
      .lineTo(0, -7.5 * k)
      .lineTo(0, 0)
      .lineTo(7.5 * k, 0)
      .lineTo(7.5 * k, -4 * k)
      .moveTo(3.5 * k, -4 * k)
      .lineTo(9 * k, -9.5 * k)
      .moveTo(5 * k, -9.5 * k)
      .lineTo(9 * k, -9.5 * k)
      .lineTo(9 * k, -5.5 * k)
  draw().stroke({ color: OUTLINE, width: 2.6, cap: "round", join: "round" })
  g.beginPath()
  draw().stroke({ color: colors.glyph, width: 1, cap: "round", join: "round" })
  return g
}

// The labels' black outline, around an emoji: a stroke outlines an emoji's picture
// badly, so eight black copies of it, a hair off in each direction, sit behind it.
const OUTLINE = "#000000"
function outlined(text: Text): Container {
  const row = new Container({ eventMode: "none" })
  for (let i = 0; i < 8; i++) {
    const a = (i * Math.PI) / 4
    const copy = emojiText(text.text)
    copy.tint = 0x000000
    copy.position.set(Math.cos(a) * 0.9, Math.sin(a) * 0.9)
    row.addChild(copy)
  }
  row.addChild(text)
  return row
}

function emojiText(text: string): Text {
  return new Text({
    eventMode: "none",
    text,
    anchor: { x: 0, y: 1 },
    style: { fontSize: EMOJI_FONT, fontFamily: EMOJI_FONTS, letterSpacing: -1.5 },
    resolution: window.devicePixelRatio * 4,
  })
}

// The body font has no ⚓: left to fall back, it came out as a grey text glyph next to
// a colour emoji.
const EMOJI_FONTS = '"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif'
// \uFE0F: the emoji, not the text glyph.
const ANCHOR = "\u2693\uFE0F"
const SHORT = "\u{1F3AC}"

export class NoteBadge extends Container {
  private picture: Graphics | null
  private links: Container | null // the link glyph, ×N
  private anchors: Container | null // 🎬×N ⚓×N

  constructor(badges: Badges, colors: BadgeColors) {
    super({ eventMode: "passive" })
    const moments = badges.anchors ?? 0
    const shorts = badges.shorts ?? 0
    this.picture = badges.img ? picture(colors) : null
    if (this.picture) namedAfterAWhile(this.picture, "Screenshot")
    this.links = badges.links > 0 ? times(badges.links, colors) : null
    this.anchors = moments + shorts > 0 ? anchors(moments, shorts, colors) : null
    // addChild() with no child throws
    for (const child of [this.picture, this.links, this.anchors]) if (child) this.addChild(child)
  }

  // The dot is at (x, y) with radius r. Around it, each at its middle: the picture on
  // its left, the ⚓🎬 row on its right, mirroring it, and the links right above it
  // (Victor, 2026-10-23 - they sat at 45° on the rim, the picture up-left, the links
  // up-right).
  place(x: number, y: number, r: number) {
    const gap = 1.5
    this.position.set(x, y)
    // As far from the dot as the link glyph above it (Victor, 2026-10-23).
    this.picture?.position.set(-r - gap - 1.5 - PICTURE_W * PICTURE_SCALE, (PICTURE_H * PICTURE_SCALE) / 2)
    this.anchors?.position.set(r + gap, (this.anchors?.height ?? 0) / 2) // its line box, bottom-anchored
    // The glyph's box centred over the dot, its arrow left out of the reckoning; its ×N,
    // when there, sticks out to the right.
    // As far from the dot as the ⚓🎬 row: the glyph's outline takes some of the gap.
    this.links?.position.set(-LINK_BOX / 2, -r - gap - 1.5)
  }
}

export function makeBadge(badges: Badges | undefined, colors: BadgeColors): NoteBadge | null {
  return badges && (badges.img || badges.links + (badges.anchors ?? 0) + (badges.shorts ?? 0) > 0)
    ? new NoteBadge(badges, colors)
    : null
}

// A badge says what it is when the pointer rests on it for 1.5 s (Victor, 2026-10-23):
// "Screenshot", "Link", "Short", "Emotional anchor", "Favorite" (graph-takeaway.ts). In
// the look of the app's tooltips (static/tooltip.js), which only reach DOM elements.
const NAME_DELAY_MS = 1500
let nameTip: HTMLDivElement | null = null
let nameTimer = 0

export function namedAfterAWhile(target: Container, name: string) {
  target.eventMode = "static"
  target.on("pointerover", (e) => {
    window.clearTimeout(nameTimer)
    const { clientX: x, clientY: y } = e
    nameTimer = window.setTimeout(() => showName(name, x, y), NAME_DELAY_MS)
  })
  target.on("pointerout", hideName)
  target.on("pointerdown", hideName)
}

function showName(name: string, x: number, y: number) {
  nameTip ??= document.body.appendChild(Object.assign(document.createElement("div"), { className: "graph-badge-name" }))
  nameTip.textContent = name
  nameTip.style.left = `${x}px`
  nameTip.style.top = `${y - 14}px`
  nameTip.classList.add("visible")
}

function hideName() {
  window.clearTimeout(nameTimer)
  nameTip?.classList.remove("visible")
}
