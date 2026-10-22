// Badges on the graph's dots, so a reader sees at a glance which notes are worth
// opening: a tiny picture at the dot's top-left when the note shows a slide or a
// screenshot, at its top-right 🔗 for the note's external links, with "×3" after it
// from two up, and right of it, at mid-height, one row for its emotional anchors: ⚓ for
// each moment the summarizer tags and 🎬 for each short played in the room, ⚓⚓🎬
// (both are the same thing: a moment that moved the room). Each emoji has a dark halo
// hugging its outline, like the star's, so it reads over the takeaway glow; none, no
// row (Victor, 2026-10-23 - it was 🌐 and ⚓ with a lowered count, ⚓₂, on a disc of the
// page background, which read as a black blob on the glow; repeated chains, 🔗🔗🔗🔗,
// read as a mess; before that "↗3"). A detail, not a key number: it was "🔗3" in bold,
// which drew the eye before the note titles (Victor, 2026-10-16).
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
  count: string // the "×3" after 🔗
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
function anchors(moments: number, shorts: number, colors: BadgeColors): Container {
  return new Container({
    eventMode: "none",
    children: [emojiText(ANCHOR.repeat(moments) + SHORT.repeat(shorts), colors)],
  })
}

// Bottom-left corner at (0, 0): the emoji once, then "×n" from two up.
function times(emoji: string, n: number, colors: BadgeColors): Container {
  const row = new Container({ eventMode: "none", children: [emojiText(emoji, colors)] })
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
        stroke: { color: colors.halo, width: 3, join: "round" },
      },
      resolution: window.devicePixelRatio * 4,
    })
    // Right after the emoji's picture, about 1em wide: its measured width runs further.
    count.position.set(EMOJI_FONT + 0.5, -0.5)
    row.addChild(count)
  }
  return row
}

function emojiText(text: string, colors: BadgeColors): Text {
  return new Text({
    eventMode: "none",
    text,
    anchor: { x: 0, y: 1 },
    style: {
      fontSize: EMOJI_FONT,
      fontFamily: EMOJI_FONTS,
      letterSpacing: -1.5,
      // A stroke outlines an emoji's picture badly; a tight shadow, unshifted, rings it.
      dropShadow: { color: colors.halo, alpha: 1, blur: 1.5, distance: 0, angle: 0 },
    },
    resolution: window.devicePixelRatio * 4,
  })
}

// The body font has no ⚓: left to fall back, it came out as a grey text glyph next to
// a colour emoji.
const EMOJI_FONTS = '"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif'
// \uFE0F: the emoji, not the text glyph.
const LINK = "\u{1F517}"
const ANCHOR = "\u2693\uFE0F"
const SHORT = "\u{1F3AC}"

export class NoteBadge extends Container {
  private picture: Graphics | null
  private links: Container | null // 🔗×N
  private anchors: Container | null // ⚓⚓🎬

  constructor(badges: Badges, colors: BadgeColors) {
    super({ eventMode: "none" })
    const moments = badges.anchors ?? 0
    const shorts = badges.shorts ?? 0
    this.picture = badges.img ? picture(colors) : null
    this.links = badges.links > 0 ? times(LINK, badges.links, colors) : null
    this.anchors = moments + shorts > 0 ? anchors(moments, shorts, colors) : null
    // addChild() with no child throws
    for (const child of [this.picture, this.links, this.anchors]) if (child) this.addChild(child)
  }

  // The dot is at (x, y) with radius r. The picture's inner corner sits on the dot's
  // rim at 45° up-left, the 🔗's bottom-left corner at 45° up-right; the ⚓🎬 row right
  // of the dot, at its middle height, always there (Victor, 2026-10-23 - it was under
  // the 🔗, wherever that left room). Over a ⚓ row the 🔗 rises clear of it.
  place(x: number, y: number, r: number) {
    const rim = r * Math.SQRT1_2
    this.position.set(x, y)
    this.picture?.position.set(-rim - 0.5 - PICTURE_W, -rim - 0.5)
    const anchorsBottom = EMOJI_FONT / 2
    this.anchors?.position.set(r + 1.5, anchorsBottom)
    const linksBottom = -rim + 1.5
    this.links?.position.set(rim - 0.5, this.anchors ? Math.min(linksBottom, anchorsBottom - EMOJI_FONT - 1) : linksBottom)
  }
}

export function makeBadge(badges: Badges | undefined, colors: BadgeColors): NoteBadge | null {
  return badges && (badges.img || badges.links + (badges.anchors ?? 0) + (badges.shorts ?? 0) > 0)
    ? new NoteBadge(badges, colors)
    : null
}
