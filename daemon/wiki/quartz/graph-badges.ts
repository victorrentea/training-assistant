// Badges on the graph's dots, so a reader sees at a glance which notes are worth
// opening: a tiny picture left of the dot when the note shows a slide or a screenshot,
// above it a link glyph (a box with an arrow leaving it) for the note's external links,
// with "×3" after it from two up, and right of it, at mid-height, one row for its
// emotional anchors: ⚓ for each moment the summarizer tags and 🎬 for each short played
// in the room, ⚓⚓🎬 (both are the same thing: a moment that moved the room). Each has
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
  img: string // the picture glyph
  link: string // the link glyph
  count: string // the "×3" after it
  halo: string // the page background, behind the picture so edges don't run through it
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
const EMOJI_FONT = 9

// Frame, mountain and sun: a picture, drawn rather than the 🖼️ emoji, which is
// mush at this size and can't take the theme's colours.
function picture(colors: BadgeColors): Graphics {
  const w = PICTURE_W
  const h = PICTURE_H
  return new Graphics({ eventMode: "none" })
    .roundRect(-1, -h - 1, w + 2, h + 2, 2.5)
    .fill({ color: colors.halo })
    .roundRect(0, -h, w, h, 1.5)
    .stroke({ color: colors.img, width: 1.1, alignment: 1 })
    .poly([1, -1, 4.2, -5, 6.2, -3, 7.3, -4.1, w - 1, -1])
    .fill({ color: colors.img })
    .circle(7.3, -h + 2.4, 1)
    .fill({ color: colors.img })
}

// Bottom-left corner at (0, 0): ⚓ per moment, then 🎬 per short.
function anchors(moments: number, shorts: number): Container {
  return outlined(emojiText(ANCHOR.repeat(moments) + SHORT.repeat(shorts)))
}

// Bottom-left corner at (0, 0): the link glyph, then "×n" from two up.
function times(n: number, colors: BadgeColors): Container {
  const row = new Container({ eventMode: "none", children: [linkGlyph(colors)] })
  if (n > 1) {
    const count = new Text({
      eventMode: "none",
      text: `×${n}`,
      anchor: { x: 0, y: 1 },
      style: {
        fontSize: EMOJI_FONT * 0.8,
        fontWeight: "600",
        fill: colors.count,
        fontFamily: colors.font,
        stroke: { color: OUTLINE, width: 2.5, join: "round" },
      },
      resolution: window.devicePixelRatio * 4,
    })
    count.position.set(LINK_W + 1.5, 0.5)
    row.addChild(count)
  }
  return row
}

// A box with an arrow leaving it by its open top-right corner: "goes out of the wiki",
// drawn rather than the 🔗 emoji, so it takes the theme's link blue and an outline
// (Victor, 2026-10-23). Bottom-left corner at (0, 0).
const LINK_W = 9
function linkGlyph(colors: BadgeColors): Graphics {
  const g = new Graphics({ eventMode: "none" })
  const draw = () =>
    g
      .moveTo(3.5, -7.5)
      .lineTo(0, -7.5)
      .lineTo(0, 0)
      .lineTo(7.5, 0)
      .lineTo(7.5, -4)
      .moveTo(3.5, -4)
      .lineTo(LINK_W, -9.5)
      .moveTo(5, -9.5)
      .lineTo(LINK_W, -9.5)
      .lineTo(LINK_W, -5.5)
  draw().stroke({ color: OUTLINE, width: 3.6, cap: "round", join: "round" })
  g.beginPath()
  draw().stroke({ color: colors.link, width: 1.4, cap: "round", join: "round" })
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
  private anchors: Container | null // ⚓⚓🎬

  constructor(badges: Badges, colors: BadgeColors) {
    super({ eventMode: "none" })
    const moments = badges.anchors ?? 0
    const shorts = badges.shorts ?? 0
    this.picture = badges.img ? picture(colors) : null
    this.links = badges.links > 0 ? times(badges.links, colors) : null
    this.anchors = moments + shorts > 0 ? anchors(moments, shorts) : null
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
    this.picture?.position.set(-r - gap - PICTURE_W, PICTURE_H / 2)
    this.anchors?.position.set(r + gap, (this.anchors?.height ?? 0) / 2) // its line box, bottom-anchored
    if (this.links) this.links.position.set(-this.linksWidth / 2, -r - gap)
  }

  // The link glyph and its ×N, when there.
  private get linksWidth(): number {
    const count = this.links?.children[1]
    return count ? count.x + count.width : LINK_W
  }
}

export function makeBadge(badges: Badges | undefined, colors: BadgeColors): NoteBadge | null {
  return badges && (badges.img || badges.links + (badges.anchors ?? 0) + (badges.shorts ?? 0) > 0)
    ? new NoteBadge(badges, colors)
    : null
}
