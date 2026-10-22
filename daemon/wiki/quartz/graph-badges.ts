// Badges on the graph's dots, so a reader sees at a glance which notes are worth
// opening: a tiny picture at the dot's top-left when the note shows a slide or a
// screenshot, and at its top-right a short column: 🌐 for the note's external links,
// then ⚓ under it for its emotional anchors (the ⚓ moments the summarizer tags, and
// the 🎬 shorts played in the room). Each emoji carries its count as a small lowered
// index, like ₂, only from 2 up: one link is a bare 🌐; none, no row, and the ⚓ moves
// up into the 🌐's place (Victor, 2026-10-22 - it was "↗3", a small arrow touching the
// count). A detail, not a key number: it was "🔗3" in bold, which drew the eye before
// the note titles (Victor, 2026-10-16).
//
// daemon/wiki/builder.py scans the built pages into note-badges.json at the site
// root and copies this file next to graph.inline.ts; patch-graph.py makes the graph
// load the JSON before it creates its dots, put one NoteBadge per badged dot in a
// container of its own (not the labels', which fades out when zoomed out) and place
// it in its animation loop.
import { Container, Graphics, Text } from "pixi.js"
import { FullSlug, SimpleSlug, pathToRoot, simplifySlug } from "../../util/path"

type Badges = { img: boolean; links: number; anchors?: number } // no anchors: a site built before them

export type BadgeColors = {
  img: string // the picture glyph
  link: string // the counts under 🌐 and ⚓
  halo: string // the page background, behind both so edges don't run through them
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
const INDEX_FONT = 6.5
const ROW = 10 // from one row's bottom to the next one's

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

// Bottom-left corner at (0, 0): the emoji, then its count right after it, smaller and
// lowered like a subscript. A count of 1 is left out: the emoji alone says "one".
function counted(emoji: string, n: number, colors: BadgeColors): Container {
  const text = (content: string, fontSize: number, fill: string, halo: boolean, font = colors.font) =>
    new Text({
      eventMode: "none",
      text: content,
      anchor: { x: 0, y: 1 },
      style: {
        fontSize,
        fontWeight: "500",
        fill,
        fontFamily: font,
        // A stroke outlines an emoji's picture badly: the emoji gets a disc instead.
        stroke: halo ? { color: colors.halo, width: 3, join: "round" } : undefined,
      },
      resolution: window.devicePixelRatio * 4,
    })
  const glyph = text(emoji, EMOJI_FONT, colors.link, false, EMOJI_FONTS)
  const w = glyph.width
  const h = glyph.height
  // The page background behind the emoji, so edges don't run through it.
  const disc = new Graphics({ eventMode: "none" })
    .circle(w / 2, -h / 2, Math.max(w, h) / 2)
    .fill({ color: colors.halo })
  const row = new Container({ eventMode: "none", children: [disc, glyph] })
  if (n > 1) {
    const index = text(`${n}`, INDEX_FONT, colors.link, true)
    // Right after the emoji's picture, which is about 1em wide: its measured width runs
    // further, and the index stood apart from it. Its bottom under the emoji's.
    index.position.set(EMOJI_FONT + 0.3, INDEX_FONT * 0.55)
    row.addChild(index)
  }
  return row
}

// The body font has no ⚓: left to fall back, it came out as a grey text glyph next to
// a colour 🌐.
const EMOJI_FONTS = '"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif'
// \uFE0F: the emoji, not the text glyph.
const GLOBE = "\u{1F310}"
const ANCHOR = "\u2693\uFE0F"

export class NoteBadge extends Container {
  private picture: Graphics | null
  private rows: Container[] // 🌐 then ⚓, top to bottom, only those with a count

  constructor(badges: Badges, colors: BadgeColors) {
    super({ eventMode: "none" })
    this.picture = badges.img ? picture(colors) : null
    this.rows = [
      badges.links > 0 ? counted(GLOBE, badges.links, colors) : null,
      (badges.anchors ?? 0) > 0 ? counted(ANCHOR, badges.anchors!, colors) : null,
    ].filter((row): row is Container => row !== null)
    if (this.picture) this.addChild(this.picture)
    this.rows.forEach((row) => this.addChild(row)) // addChild() with no child throws
  }

  // The dot is at (x, y) with radius r. The picture's inner corner sits on the dot's
  // rim, at 45° up-left; the first row's bottom-left corner at 45° up-right, and the
  // rows below it keep its left edge, moved out just enough to clear the dot.
  place(x: number, y: number, r: number) {
    const rim = r * Math.SQRT1_2
    this.position.set(x, y)
    this.picture?.position.set(-rim - 0.5 - PICTURE_W, -rim - 0.5)
    const top = -rim + 1.5
    let left = rim - 0.5
    for (let i = 1; i < this.rows.length; i++) {
      const bottom = top + i * ROW
      const nearest = bottom - ROW < 0 && bottom > 0 ? 0 : Math.min(Math.abs(bottom), Math.abs(bottom - ROW))
      if (nearest < r) left = Math.max(left, Math.sqrt(r * r - nearest * nearest) + 1)
    }
    this.rows.forEach((row, i) => row.position.set(left, top + i * ROW))
  }
}

export function makeBadge(badges: Badges | undefined, colors: BadgeColors): NoteBadge | null {
  return badges && (badges.img || badges.links > 0 || (badges.anchors ?? 0) > 0)
    ? new NoteBadge(badges, colors)
    : null
}
