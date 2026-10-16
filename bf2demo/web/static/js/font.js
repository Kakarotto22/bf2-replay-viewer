// The game's own bitmap fonts (Fonts_client.zip `.dif` metrics + `.dds` atlas, served as JSON + PNG). The glyphs are white on transparent;
// they are tinted per colour and drawn with a 1 px black outline like the game's outlined lists. A glyph row is
// `[f1, f2, f3, y offset, x0, y0, x1, y1]`: f1 = left bearing, f2 = advance, f3 = right bearing, the pen moves by f1 + f2 + f3 (checked on the width of game text and of the digits in a game video).
import { api } from "./util.js";

const fonts = new Map();            // name -> { meta, img, tints: Map<color, canvas> } | null (unavailable)

export async function loadFonts(names) {
  await Promise.all(names.map(async (name) => {
    if (fonts.has(name)) return;
    fonts.set(name, null);
    try {
      const meta = (await api("/api/fonts/" + name + ".json")).json;
      const img = new Image(); img.src = "/api/fonts/" + name + ".png";
      await new Promise((ok, no) => { img.onload = ok; img.onerror = no; });
      fonts.set(name, { meta, img, tints: new Map(), glyphs: new Map() });
    } catch (e) { fonts.set(name, null); }
  }));
}
export const hasFont = (name) => !!fonts.get(name);
/** True when the font has a glyph for every character of `text` (names in other scripts fall back to the page's font). */
export function canDraw(name, text) { const f = fonts.get(name); if (!f) return false; for (const ch of text) if (!f.meta.glyphs[ch.codePointAt(0)] && ch !== " ") return false; return true; }

function tinted(f, color) {
  let c = f.tints.get(color);
  if (!c) {
    c = document.createElement("canvas"); c.width = f.img.width; c.height = f.img.height;
    const g = c.getContext("2d");
    g.drawImage(f.img, 0, 0);
    g.globalCompositeOperation = "source-in"; g.fillStyle = color; g.fillRect(0, 0, c.width, c.height);
    f.tints.set(color, c);
  }
  return c;
}

const advance = (g) => g[0] + g[1] + g[2];            // left bearing + advance + right bearing (checked on the width of game text and of the digits in a game video)

/** Width of `text` in font pixels. */
export function textWidth(name, text) {
  const f = fonts.get(name); if (!f) return text.length * 6;
  let w = 0;
  for (const ch of text) { const g = f.meta.glyphs[ch.codePointAt(0)]; w += g ? advance(g) : 3; }
  return w;
}
export const lineHeight = (name) => { const f = fonts.get(name); return f ? Math.ceil(f.meta.line) : 12; };

/**
 * Draw a run of text at (x, y) = top-left, font pixels times `scale`; returns the x after it. The game draws its glyph quads with bilinear
 * filtering, so the atlas is smoothed when it is scaled (`smooth`), never nearest-neighbour blocks.
 */
export function drawText(g, name, text, x, y, color, scale = 1, outline = true, smooth = true) {
  const f = fonts.get(name); if (!f) return x;
  g.imageSmoothingEnabled = smooth; g.imageSmoothingQuality = "high";
  const ring = Math.max(1, Math.round(scale));                  // the outline is one device pixel wide at least
  let pen = x;
  for (const ch of text) {
    const code = ch.codePointAt(0), gl = f.meta.glyphs[code];
    if (!gl) { pen += 3 * scale; continue; }
    const [, , , yo, x0, y0, x1, y1] = gl, w = x1 - x0, h = y1 - y0;
    if (w > 0 && h > 0) {
      // the glyph canvases carry a 1 px transparent margin (no bleeding of the neighbours in the atlas); the rectangle is snapped to whole device
      // pixels at both edges so every glyph is resampled the same way and the line does not shimmer at fractional factors
      const left = Math.round(pen + (gl[0] - 1) * scale), top = Math.round(y + (yo - 1) * scale);
      const dw = Math.round(pen + (gl[0] + w + 1) * scale) - left, dh = Math.round(y + (yo + h + 1) * scale) - top;
      if (outline) { const shade = glyph(f, "#000000", code, x0, y0, w, h); for (const [ox, oy] of RING) g.drawImage(shade, left + ox * ring, top + oy * ring, dw, dh); }
      g.drawImage(glyph(f, color, code, x0, y0, w, h), left, top, dw, dh);
    }
    pen += advance(gl) * scale;
  }
  return pen;
}
const RING = [[-1, 0], [1, 0], [0, -1], [0, 1], [-1, -1], [1, 1], [-1, 1], [1, -1]];

function glyph(f, color, code, x0, y0, w, h) {
  const key = color + "|" + code;
  let c = f.glyphs.get(key);
  if (!c) {
    c = document.createElement("canvas"); c.width = w + 2; c.height = h + 2;
    c.getContext("2d").drawImage(tinted(f, color), x0, y0, w, h, 1, 1, w, h);
    f.glyphs.set(key, c);
  }
  return c;
}

/** Text inside a node of the HUD layout (`x`, `width`): the game's alignment codes are 0 = centre, 1 = right, 2 = left. */
export function drawIn(g, name, text, x, y, width, align, color, scale = 1, outline = true) {
  const w = textWidth(name, text) * scale, px = align === "right" ? x + width * scale - w : align === "center" ? x + (width * scale - w) / 2 : x;
  return drawText(g, name, text, px, y, color, scale, outline);
}

/** A canvas holding one line of coloured runs `[{t, c}]`; null when the font is not available (callers fall back to HTML). */
export function lineCanvas(name, runs, scale = 2) {
  const f = fonts.get(name); if (!f) return null;
  let w = 0; for (const r of runs) w += textWidth(name, r.t) * scale;
  const h = (Math.ceil(f.meta.line) + 3) * scale, c = document.createElement("canvas");
  c.width = Math.ceil(w + 4 * scale); c.height = Math.ceil(h);
  const g = c.getContext("2d"); let x = 2 * scale;
  for (const r of runs) x = drawText(g, name, r.t, x, 1 * scale, r.c, scale);
  return c;
}
