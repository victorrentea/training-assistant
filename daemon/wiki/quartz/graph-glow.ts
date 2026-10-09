// A soft glow behind each dot, as strong as its topic is common in the trainer's past
// sessions: a staple of his trainings glows, a topic new today does not.
//
// daemon/wiki/topic_frequency.py writes note-glow.json at the site root:
// {"sessions": N, "seen": {slug: n}}, n = how many of the N past sessions covered the
// note's topic. builder.py copies this file next to graph.inline.ts, and patch-graph.py
// makes the graph load the JSON, put one sprite per glowing dot in a container below
// the edges and the dots, and move it with its dot in the animation loop.
import { Sprite, Texture } from "pixi.js"
import { FullSlug, SimpleSlug, pathToRoot, simplifySlug } from "../../util/path"

type GlowJson = { sessions?: number; seen?: Record<string, number> }

const loaded = new Map<string, Promise<Map<SimpleSlug, number>>>()

// Fetched once per site, as {slug: strength in 0..1}. A site published before the glow
// existed, or one whose notes could not be scored, has no strengths: no glow.
export function loadGlow(fullSlug: FullSlug): Promise<Map<SimpleSlug, number>> {
  const url = new URL(`${pathToRoot(fullSlug)}/note-glow.json`, window.location.href).toString()
  let glow = loaded.get(url)
  if (!glow) {
    glow = fetch(url)
      .then((res) => (res.ok ? res.json() : {}))
      .catch(() => ({}))
      .then((json: GlowJson) => {
        const sessions = json.sessions ?? 0
        const strengths = new Map<SimpleSlug, number>()
        if (sessions <= 0) return strengths
        for (const [slug, seen] of Object.entries(json.seen ?? {})) {
          if (seen > 0) strengths.set(simplifySlug(slug as FullSlug), strength(seen, sessions))
        }
        return strengths
      })
    loaded.set(url, glow)
  }
  return glow
}

// Covered in 60% of past sessions or more: full glow. Slightly concave, so a topic seen
// in a couple of sessions still shows, faint, without rivalling the staples.
const FULL_AT = 0.6

function strength(seen: number, sessions: number): number {
  return Math.pow(Math.min(1, seen / (sessions * FULL_AT)), 0.75)
}

// One radial gradient, white to transparent, drawn once and tinted per theme: a sprite
// per dot then costs one quad, where stacked Graphics circles or a blur filter cost a
// lot more on a graph that redraws every frame.
let texture: Texture | null = null
const TEXTURE_SIZE = 128

function glowTexture(): Texture {
  if (texture) return texture
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = TEXTURE_SIZE
  const ctx = canvas.getContext("2d")!
  const c = TEXTURE_SIZE / 2
  const gradient = ctx.createRadialGradient(c, c, 0, c, c, c)
  gradient.addColorStop(0, "rgba(255,255,255,1)")
  gradient.addColorStop(0.3, "rgba(255,255,255,0.85)")
  gradient.addColorStop(0.6, "rgba(255,255,255,0.4)")
  gradient.addColorStop(0.85, "rgba(255,255,255,0.12)")
  gradient.addColorStop(1, "rgba(255,255,255,0)")
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, TEXTURE_SIZE, TEXTURE_SIZE)
  texture = Texture.from(canvas)
  return texture
}

// The dot has radius r; the halo reaches from about 2.5r (faint) to 8r (staple) away.
export function makeGlow(s: number | undefined, r: number, color: string): Sprite | null {
  if (!s) return null
  const glow = new Sprite({ texture: glowTexture(), anchor: 0.5, eventMode: "none", tint: color })
  const size = 2 * r * (2.5 + 5.5 * s)
  glow.width = glow.height = size
  glow.alpha = 0.3 + 0.7 * s
  return glow
}
