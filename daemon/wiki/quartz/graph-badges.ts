// Badges on the graph's dots, so a reader sees at a glance which notes are worth
// opening: a tiny picture at the dot's top-right when the note shows a slide or a
// screenshot, and at its top-left 🔗 with how many external links it holds (none: no
// badge).
//
// daemon/wiki/builder.py scans the built pages into note-badges.json at the site
// root and copies this file next to graph.inline.ts; patch-graph.py makes the graph
// load the JSON before it creates its dots, put one NoteBadge per badged dot in a
// container of its own (not the labels', which fades out when zoomed out) and place
// it in its animation loop.
import { Container, Graphics, Text } from "pixi.js"
import { FullSlug, SimpleSlug, pathToRoot, simplifySlug } from "../../util/path"

type Badges = { img: boolean; links: number }

export type BadgeColors = {
  img: string // the picture glyph
  link: string // the link count
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
const LINK_FONT = 10

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

function linkCount(n: number, colors: BadgeColors): Text {
  return new Text({
    eventMode: "none",
    text: `🔗${n}`,
    anchor: { x: 1, y: 1 },
    style: {
      fontSize: LINK_FONT,
      fontWeight: "700",
      fill: colors.link,
      fontFamily: colors.font,
      stroke: { color: colors.halo, width: 3, join: "round" },
    },
    resolution: window.devicePixelRatio * 4,
  })
}

export class NoteBadge extends Container {
  private picture: Graphics | null
  private links: Text | null

  constructor(badges: Badges, colors: BadgeColors) {
    super({ eventMode: "none" })
    this.picture = badges.img ? picture(colors) : null
    this.links = badges.links > 0 ? linkCount(badges.links, colors) : null
    if (this.picture) this.addChild(this.picture)
    if (this.links) this.addChild(this.links)
  }

  // The dot is at (x, y) with radius r. Each badge's inner corner sits on the dot's
  // rim, at 45° up-right (picture) and up-left (link count).
  place(x: number, y: number, r: number) {
    const rim = r * Math.SQRT1_2
    this.position.set(x, y)
    this.picture?.position.set(rim + 0.5, -rim - 0.5)
    this.links?.position.set(-rim + 0.5, -rim + 1.5)
  }
}

export function makeBadge(badges: Badges | undefined, colors: BadgeColors): NoteBadge | null {
  return badges && (badges.img || badges.links > 0) ? new NoteBadge(badges, colors) : null
}
