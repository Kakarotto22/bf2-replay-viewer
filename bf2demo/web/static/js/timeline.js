// Round timeline under the map: ticket curves, who held each control point, kill ticks and the playhead. The static part is
// rendered once into an offscreen canvas; a frame only copies it and draws the playhead.
import { M } from "./model.js";
import { TEAM_COL } from "./palette.js";
import { S } from "./state.js";
import { $, clamp } from "./util.js";

let canvas, bg = null, dpr = 1;

export function initTimeline(onSeek) {
  canvas = $("timeline");
  let down = false;
  const at = (e) => { const r = canvas.getBoundingClientRect(); onSeek(M.tMin + clamp((e.clientX - r.left) / r.width, 0, 1) * (M.tMax - M.tMin)); };
  canvas.onpointerdown = (e) => { down = true; canvas.setPointerCapture(e.pointerId); at(e); };
  canvas.onpointermove = (e) => { if (down) at(e); };
  canvas.onpointerup = () => { down = false; };
}

export function resizeTimeline() {
  dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
  bg = null;
}

function renderBackground() {
  const w = canvas.width, h = canvas.height, c = document.createElement("canvas"); c.width = w; c.height = h;
  const g = c.getContext("2d"), d = dpr, span = Math.max(1, M.tMax - M.tMin), x = (t) => ((t - M.tMin) / span) * w;
  g.fillStyle = "#10151d"; g.fillRect(0, 0, w, h);
  const top = 4 * d, tkH = h * 0.5, tickets = {};
  for (const t in M.doc.tickets) tickets[t] = M.doc.tickets[t].filter((row, i) => !(i === 0 && row[1] === 0));      // the first 0 is the ScoreManager's default, not a count
  let tmax = 1; for (const t in tickets) for (const [, v] of tickets[t]) tmax = Math.max(tmax, v);
  for (const t in tickets) {                                        // step curves
    g.strokeStyle = TEAM_COL[t]; g.lineWidth = 1.6 * d; g.beginPath();
    let lastY = null;
    for (const [tk, v] of tickets[t]) {
      const px = x(Math.max(M.tMin, tk)), py = top + tkH * (1 - v / tmax);
      if (lastY === null) g.moveTo(px, py); else { g.lineTo(px, lastY); g.lineTo(px, py); }
      lastY = py;
    }
    if (lastY !== null) g.lineTo(w, lastY);
    g.stroke();
  }
  g.fillStyle = "#ffffff55"; for (const k of M.kills) g.fillRect(x(k.tick), top + tkH + 2 * d, Math.max(1, d), 5 * d);
  const cps = M.doc.control_points, strip = top + tkH + 9 * d, rowH = Math.max(2 * d, (h - strip - 3 * d) / Math.max(1, cps.length));
  cps.forEach((cp, i) => {
    let prev = cp.initial_team, from = M.tMin;
    const seg = (to, team) => { g.fillStyle = (TEAM_COL[team] || TEAM_COL[0]) + "cc"; g.fillRect(x(from), strip + i * rowH, Math.max(1, x(to) - x(from)), rowH - 1); };
    for (const [tk, team] of cp.history) { if (tk > from) seg(tk, prev); from = Math.max(from, tk); prev = team; }
    seg(M.tMax, prev);
  });
  return c;
}

export function drawTimeline() {
  if (!canvas || !M) return;
  if (!bg) bg = renderBackground();
  const g = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
  g.drawImage(bg, 0, 0);
  if (S.moments && S.moments.length) {                            // the kills picked by the Moments filter
    g.fillStyle = "#4fc3a1";
    for (const t of S.moments) g.fillRect(((t - M.tMin) / Math.max(1, M.tMax - M.tMin)) * w - dpr, 0, 3 * dpr, h * 0.62);
  }
  g.fillStyle = "#fff"; g.fillRect(((S.tick - M.tMin) / Math.max(1, M.tMax - M.tMin)) * w - dpr, 0, 2 * dpr, h);
}
export const dropTimelineCache = () => { bg = null; };
