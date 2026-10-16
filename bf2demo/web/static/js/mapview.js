// The map canvas: backdrop, control points, units drawn with the game's minimap icons, trail, kill lines, heatmap.
import { ICON, flagKey, nativeSize, plain, sprite, spriteRect, squadIconKey, vehicleIconKey, vehicleInfo } from "./assets.js";
import { canDraw, drawText, textWidth } from "./font.js";
import { vehicleLabel } from "./text.js";
import { M, activeTracks, isCommander, isCorpse, isLeader, isLive, kitOf, occupants, playerPos, samplePos, seatOf, squadOf, teamOfPlayer, trackTeam } from "./model.js";
import { KIT_COL, SQUAD, TEAM_COL, squadColor } from "./palette.js";
import { S, invalidate } from "./state.js";
import { TPS, bsearch, clamp, histAt } from "./util.js";

const GAP_JUMP = 120;                         // metres: a trail never joins two samples further apart than this

export const V = { canvas: null, ctx: null, W: 0, H: 0, dpr: 1, worldSize: 2048, backdrop: null, hd: null };
export const FRAME = { alive: { 1: 0, 2: 0 }, crews: 0 };       // counted over the whole map, not only the visible part
export const PERF = { ms: 0, frames: 0, samples: [], resizes: 0 };

// hit targets of the last frame (parallel arrays: no allocation per frame)
const HIT = { n: 0, x: new Float32Array(4096), y: new Float32Array(4096), r: new Float32Array(4096), tr: new Array(4096) };
const pos = { x: 0, z: 0, h: -1, gap: false };
let heatCanvas = null, heatKey = "";

export function initMap(canvas) { V.canvas = canvas; V.ctx = canvas.getContext("2d"); }
export function setBackdrop(image, worldSize) { V.backdrop = image; V.hd = null; V.hdLevel = null; V.hdFull = false; V.worldSize = worldSize; heatKey = ""; }

/** A phone: its 4096 px HD terrain (3 - 6 MB, about 64 MB decoded) is not loaded until the user asks for the detailed map. */
export const smallDevice = () => Math.min(screen.width, screen.height) < 600 || (navigator.deviceMemory || 8) <= 4;
/**
 * Fetch the high resolution terrain of `level` (404 for levels without one: the minimap stays). A phone gets the 2048 px version (about 0.5 MB, drawn
 * as soon as it arrives over the minimap) and the full 4096 px one only after the user zooms in far.
 */
export function loadHd(level, full = !smallDevice()) {
  if (V.hdLevel === level && (V.hdFull || !full)) return;
  V.hdLevel = level; V.hdFull = full;
  const hd = new Image();
  hd.onload = () => { if (V.hdLevel === level && V.hdFull === full) { V.hd = hd; invalidate(); } };
  hd.src = "/api/maps/" + level + "/hd.jpg" + (full ? "" : "?size=2048");
}

export function resizeMap(w, h) {
  V.dpr = window.devicePixelRatio || 1; V.W = w; V.H = h;
  const cw = Math.min(8192, Math.max(1, Math.round(w * V.dpr))), ch = Math.min(8192, Math.max(1, Math.round(h * V.dpr)));
  PERF.resizes++;
  if (V.canvas.width !== cw) V.canvas.width = cw;                   // assigning the size clears the canvas and reallocates it: only when it changed
  if (V.canvas.height !== ch) V.canvas.height = ch;
  invalidate();
}
const scaleK = () => (Math.min(V.W, V.H) / V.worldSize) * S.view.zoom;
export const w2sx = (x) => V.W / 2 + (x - S.view.cx) * scaleK();
export const w2sy = (z) => V.H / 2 - (z - S.view.cz) * scaleK();
export const s2w = (sx, sy) => { const k = scaleK(); return [S.view.cx + (sx - V.W / 2) / k, S.view.cz - (sy - V.H / 2) / k]; };

export function zoomAt(sx, sy, factor) {
  const before = s2w(sx, sy);
  S.view.zoom = clamp(S.view.zoom * factor, 0.6, 60);
  if (S.view.zoom > 2.5 && V.hdLevel && !V.hdFull && S.layers.hd) loadHd(V.hdLevel, true);            // zoomed in on a phone: now the sharp full map is worth its size
  const after = s2w(sx, sy);
  S.view.cx += before[0] - after[0]; S.view.cz += before[1] - after[1];
  invalidate();
}

// ---------------------------------------------------------------------------------------------------------- filters
function playerOk(p, tick) {
  if (!p) return true;
  const kit = kitOf(p, tick);
  if (kit != null && S.kits[kit] === false) return false;
  if (S.squad !== "all") { const sq = squadOf(p, tick); if (S.squad === "none" ? sq !== 0 : sq !== +S.squad) return false; }
  return true;
}
/** A soldier's label colour = the colour of his marker (the selected player's own squad is green). */
const colour2 = (col, p, tick) => (ownSquad(p, tick) ? SQUAD : col);
function unitColor(tr, tick, team, p) {
  if (S.color === "squad" && p) return squadColor(squadOf(p, tick));
  if (S.color === "kit" && p) { const k = kitOf(p, tick); if (k != null) return KIT_COL[k % 7]; }
  return TEAM_COL[team] || TEAM_COL[0];
}

// -------------------------------------------------------------------------------------------------------- heatmap
function heatmap() {
  const key = [V.worldSize, S.teams[1], S.teams[2], M.kills.length].join("|");
  if (key === heatKey) return heatCanvas;
  heatKey = key;
  const N = 1024, c = heatCanvas || (heatCanvas = document.createElement("canvas"));
  c.width = c.height = N;
  const g = c.getContext("2d"); g.clearRect(0, 0, N, N); g.globalCompositeOperation = "lighter";
  const u = N / V.worldSize, r = Math.max(14, N * 0.02);
  for (const k of M.kills) {
    if (!k.hasV) continue;
    const p = M.players.get(k.v), team = p ? teamOfPlayer(p, k.tick) : 0;
    if (S.teams[team] === false) continue;
    const x = (k.vx + V.worldSize / 2) * u, y = (V.worldSize / 2 - k.vz) * u;
    const grad = g.createRadialGradient(x, y, 0, x, y, r);
    grad.addColorStop(0, "rgba(255,90,40,.30)"); grad.addColorStop(1, "rgba(255,90,40,0)");
    g.fillStyle = grad; g.fillRect(x - r, y - r, 2 * r, 2 * r);
  }
  return c;
}

// ------------------------------------------------------------------------------------------------------------ draw
export function drawMap() {
  const t0 = performance.now();
  const { ctx, W, H, dpr } = V, tick = S.tick | 0;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  if (S.follow && S.sel != null && playerPos(S.sel, tick, pos)) { S.view.cx = pos.x; S.view.cz = pos.z; }
  const k = scaleK(), bx = w2sx(-V.worldSize / 2), by = w2sy(V.worldSize / 2), bs = V.worldSize * k;
  drawBackdrop(bx, by, bs, k);
  if (S.layers.heat) { ctx.globalAlpha = 0.9; ctx.drawImage(heatmap(), bx, by, bs, bs); ctx.globalAlpha = 1; }
  if (S.layers.strikes) drawStrikes(tick, k);
  if (S.layers.cps) drawControlPoints(tick, k);
  if (S.layers.trail && S.sel != null) drawTrail(tick);
  if (S.layers.lines) drawKillLines(tick);
  drawUnits(tick, k);
  PERF.samples.push(performance.now() - t0); if (PERF.samples.length > 60) PERF.samples.shift();
  PERF.frames++; PERF.ms = PERF.samples.reduce((a, b) => a + b, 0) / PERF.samples.length;
}

function drawBackdrop(bx, by, bs, k) {
  const { ctx } = V;
  const image = (S.layers.hd && V.hd) || V.backdrop;                // the detailed terrain once it has arrived, the game's minimap otherwise
  if (image) { ctx.drawImage(image, bx, by, bs, bs); ctx.fillStyle = "rgba(0,0,0,.16)"; ctx.fillRect(bx, by, bs, bs); }
  else {
    ctx.fillStyle = "#0e141c"; ctx.fillRect(bx, by, bs, bs); ctx.strokeStyle = "#1e2835"; ctx.lineWidth = 1; ctx.beginPath();
    for (let i = 0; i <= 16; i++) { const p = (i * bs) / 16; ctx.moveTo(bx + p, by); ctx.lineTo(bx + p, by + bs); ctx.moveTo(bx, by + p); ctx.lineTo(bx + bs, by + p); }
    ctx.stroke();
  }
  ctx.strokeStyle = "#2a3441"; ctx.lineWidth = 1; ctx.strokeRect(bx, by, bs, bs);
}

function drawControlPoints(tick, k) {
  const { ctx } = V, px = 32 * (Math.min(V.W, V.H) / 512) * S.iconScale, showNames = S.layers.names && S.view.zoom >= 1.4;
  for (const cp of M.doc.control_points) {
    const team = histAt(cp.history, tick, cp.initial_team), x = w2sx(cp.position[0]), y = w2sy(cp.position[2]);
    if (x < -50 || y < -50 || x > V.W + 50 || y > V.H + 50) continue;
    const col = TEAM_COL[team] || TEAM_COL[0], flag = plain(flagKey(M.teamNames[team], team === 1 || team === 2, M.uncapturable.has((cp.template || "").toLowerCase())));
    if (flag) ctx.drawImage(flag, x - px / 2, y - px / 2, px, px);        // the game draws the flat flag only, no ring
    else { ctx.fillStyle = col; ctx.font = "bold 14px Segoe UI, sans-serif"; ctx.textAlign = "center"; ctx.fillText("⚑", x, y + 5); }
    if (showNames) label(cp.label || cpName(cp), x, y + px * 0.85, CP_NAME);
  }
}
export const cpName = (cp) => (cp.template || "").replace(/^cpname_[a-z0-9]+_\d+_/i, "").replace(/^\d+_[a-z]+_cp_/i, "").replace(/_/g, " ");

// Names on the map use the game's own bitmap font (the outlined chat font, same as the kill feed) in the unit's colour, one game pixel = `ik` map pixels.
const NAME_FONT = "ingameChatFontLocalOutline_8", CP_NAME = "#FFCA0B";
function label(text, x, y, color) {
  const { ctx } = V, ik = (Math.min(V.W, V.H) / 512) * S.iconScale;
  if (canDraw(NAME_FONT, text)) { drawText(ctx, NAME_FONT, text, Math.round(x - (textWidth(NAME_FONT, text) * ik) / 2), Math.round(y - 9 * ik), color, ik); return; }
  ctx.font = "11px Segoe UI, Tahoma, sans-serif"; ctx.textAlign = "center";
  ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,.75)"; ctx.strokeText(text, x, y); ctx.fillStyle = color; ctx.fillText(text, x, y);
}

function drawTrail(tick) {
  const { ctx } = V, from = tick - 30 * TPS, pts = [];
  const add = (tr, a, b) => {
    const i0 = Math.max(0, bsearch(tr.t, a)), i1 = bsearch(tr.t, b);
    for (let i = i0; i <= i1; i++) {
      if (tr.t[i] < a) continue;
      if (pts.length && (tr.t[i] - pts[pts.length - 3] > 90 || Math.hypot(tr.x[i] - pts[pts.length - 2], tr.z[i] - pts[pts.length - 1]) > GAP_JUMP)) pts.push(NaN, NaN, NaN);
      pts.push(tr.t[i], tr.x[i], tr.z[i]);
    }
  };
  const seats = M.seatsOf.get(S.sel) || [];
  const segs = [];
  for (const tr of M.byOwner.get(S.sel) || []) if (tr.t0 <= tick && tr.last >= from) segs.push([tr, Math.max(from, tr.t0), tick]);
  for (const s of seats) if (s.a <= tick && s.b >= from) segs.push([s.track, Math.max(from, s.a), Math.min(tick, s.b)]);
  segs.sort((a, b) => a[1] - b[1]);
  for (const [tr, a, b] of segs) add(tr, a, b);
  ctx.lineWidth = 2.2; ctx.lineJoin = "round"; ctx.lineCap = "round";
  for (let i = 3; i < pts.length; i += 3) {
    if (pts[i] !== pts[i] || pts[i - 3] !== pts[i - 3]) continue;
    const age = (tick - pts[i]) / (30 * TPS);
    ctx.strokeStyle = `rgba(255,255,255,${clamp(0.85 - age * 0.8, 0.05, 0.85)})`;
    ctx.beginPath(); ctx.moveTo(w2sx(pts[i - 2]), w2sy(pts[i - 1])); ctx.lineTo(w2sx(pts[i + 1]), w2sy(pts[i + 2])); ctx.stroke();
  }
}

function drawKillLines(tick) {
  const { ctx } = V, life = 2 * TPS * Math.max(1, S.playing ? S.speed / 2 : 1);
  for (let i = bsearch(M.killTicks, tick); i >= 0; i--) {
    const kl = M.kills[i], age = tick - kl.tick;
    if (age > life) break;
    if (!kl.hasK || !kl.hasV || kl.k === kl.v) continue;
    const a = 1 - age / life, ax = w2sx(kl.kx), ay = w2sy(kl.kz), bx = w2sx(kl.vx), by = w2sy(kl.vz);
    ctx.strokeStyle = kl.tk ? `rgba(255,200,60,${a})` : `rgba(255,255,255,${a * 0.8})`; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    ctx.strokeStyle = `rgba(255,70,50,${a})`; ctx.lineWidth = 2.2; ctx.beginPath();
    ctx.moveTo(bx - 5, by - 5); ctx.lineTo(bx + 5, by + 5); ctx.moveTo(bx + 5, by - 5); ctx.lineTo(bx - 5, by + 5); ctx.stroke();
  }
}

function drawSprite(key, color, px, x, y, angle, alpha) {
  const { ctx, dpr } = V, s = sprite(key, color, px * dpr);
  if (!s) return false;
  if (alpha !== 1) ctx.globalAlpha = alpha;
  if (angle >= 0) { ctx.save(); ctx.translate(x, y); ctx.rotate((angle * Math.PI) / 180); ctx.drawImage(s, -px / 2, -px / 2, px, px); ctx.restore(); }
  else ctx.drawImage(s, x - px / 2, y - px / 2, px, px);
  if (alpha !== 1) ctx.globalAlpha = 1;
  return true;
}

function drawUnits(tick, k) {
  const { ctx } = V, near = S.view.zoom;
  // BF2.exe (the player drawing function and the icon chooser): every marker is a quad of its texture's own size - soldier 16, squad 15,
  // vehicle 16, commander 32 - on the 512 px map node, whatever the zoom. Our map at zoom 1 is min(W, H) px wide, so one game pixel is `ik`.
  const ik = (Math.min(V.W, V.H) / 512) * S.iconScale, px = 16 * ik, sp = 16 * ik, vpx = 16 * ik * 1.0;
  FRAME.alive[1] = FRAME.alive[2] = 0; FRAME.crews = 0; HIT.n = 0;
  const list = activeTracks(tick), wantNames = S.layers.names && near >= 2.2;
  const pass = (tr) => S.kinds[tr.kind] !== false;
  // vehicles are drawn above soldiers, so soldiers first
  for (let pass2 = 0; pass2 < 2; pass2++) for (let i = 0; i < list.length; i++) {
    const tr = list[i];
    if ((pass2 === 0) === (tr.kind === "vehicle")) continue;
    const live = isLive(tr, tick), corpse = !live && isCorpse(tr, tick);
    if (!live && !corpse) continue;
    if (tr.kind === "soldier") {
      const seat = seatOf(tr.owner, tick);
      if (live && seat) continue;                                          // inside a vehicle or parachute: the vehicle represents them
      const p = M.players.get(tr.owner), team = p ? teamOfPlayer(p, tick) : tr.team;
      if (live && team !== 0 && S.teams[team] !== false) { FRAME.alive[team] = (FRAME.alive[team] || 0) + 1; }
      if (!pass(tr) || S.teams[team] === false || !playerOk(p, tick)) continue;
      samplePos(tr, clamp(tick, tr.t0, tr.last), pos);
      const x = w2sx(pos.x), y = w2sy(pos.z);
      if (x < -20 || y < -20 || x > V.W + 20 || y > V.H + 20) continue;
      if (corpse) { if (S.layers.corpses) drawDeath(x, y); continue; }
      const col = unitColor(tr, tick, team, p), sel = S.sel === tr.owner, alpha = pos.gap ? 0.4 : 1;
      drawPerson(p, tick, x, y, pos.h, col, alpha, sel, ik, sp);
      if (sel) ring(x, y, sp * 0.8);
      hit(x, y, Math.max(sp * 0.7, 8), tr);
      if (sel || S.hover === tr || wantNames) label(p ? p.name.trim() : tr.tpl, x, y - sp * 1.1, colour2(col, p, tick));
    } else if (tr.kind === "vehicle") {
      const crew = occupants(tr, tick), empty = crew.length === 0;
      if (empty && !S.kinds.empty) continue;
      if (!empty && S.kinds.vehicle === false) continue;
      const team = trackTeam(tr, tick);
      if (!empty) FRAME.crews++;
      if (S.teams[team] === false && !empty) continue;
      if (!empty && !crew.some((pid) => playerOk(M.players.get(pid), tick))) continue;
      samplePos(tr, clamp(tick, tr.t0, tr.last), pos);
      const x = w2sx(pos.x), y = w2sy(pos.z);
      if (x < -30 || y < -30 || x > V.W + 30 || y > V.H + 30) continue;
      const sel = crew.includes(S.sel), size = vpx;
      const info = vehicleInfo(tr.tpl), hasIcon = !!(info && info.icon);
      if (!hasIcon && !empty) {                       // a static weapon (TOW, AA gun ...) has no minimap icon: its gunner shows as a walking soldier
        crew.forEach((pid, i) => { const q = M.players.get(pid); drawPerson(q, tick, x + i * sp * 0.4, y, pos.h, unitColor(tr, tick, team, q), 1, pid === S.sel, ik, sp); });
        hit(x, y, sp * 0.7, tr);
        if (sel || S.hover === tr || wantNames) label(crewLabel(crew, tr), x, y - sp * 1.1, unitColor(tr, tick, team, M.players.get(crew[0])));
        continue;
      }
      const ownCrew = !empty && crew.some((pid) => ownSquad(M.players.get(pid), tick));
      const col = empty ? "#b3b3b3" : ownCrew ? SQUAD : TEAM_COL[team] || TEAM_COL[0];   // empty: glyph x 0.7 grey; the selected player's squad is green
      if (sel && pos.h >= 0) viewCone(x, y, pos.h, ik);
      if (!drawSprite(vehicleIconKey(tr.tpl), col, size, x, y, pos.h, 1)) fallbackTri(x, y, size / 2, col, pos.h, 1);
      if (!empty) leaderOverlay(tr, crew, tick, x, y, pos.h, ik, col);
      if (sel) ring(x, y, size * 0.7);
      hit(x, y, size * 0.7, tr);
      if (!empty && (sel || S.hover === tr || wantNames)) label(crewLabel(crew, tr), x, y - size * 0.7, col);
    } else if (S.kinds.other) {
      if (tr.cls === "UAVVehicle") { drawUav(tr, tick, k, px); continue; }
      samplePos(tr, clamp(tick, tr.t0, tr.last), pos);
      const x = w2sx(pos.x), y = w2sy(pos.z);
      if (x < -20 || y < -20 || x > V.W + 20 || y > V.H + 20) continue;
      if (tr.cls === "SupplyObject") {                                       // a supply drop: the white ring and the parachute-and-crate glyph
        const ring = plain(ICON.ring);
        if (ring) ctx.drawImage(ring, x - ring.width * ik / 2, y - ring.height * ik / 2, ring.width * ik, ring.height * ik);
        drawSprite(ICON.supplies, "#ffffff", nativeSize(ICON.supplies) * ik, x, y, -1, 1);
      } else if (tr.dropped) drawSprite(ICON.vehicleDrop, "#ffffff", nativeSize(ICON.vehicleDrop) * ik, x, y, -1, 1);
      else if (tr.parachute) { const t = trackTeam(tr, tick); ctx.strokeStyle = TEAM_COL[t] || "#fff"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, y - 3, px * 0.45, Math.PI, 0); ctx.stroke(); }
      else continue;
      hit(x, y, px * 0.7, tr);
    }
  }
}

/** Crew names; the vehicle's own name only when one of the crew is the selected player (clicked). */
export const crewLabel = (crew, tr) => {
  const p = M.players.get(crew[0]), more = crew.length > 1 ? " +" + (crew.length - 1) : "";
  return (p ? p.name : "?") + more + (crew.includes(S.sel) ? "  [" + vehicleLabel(tr.tpl) + "]" : "");
};

/**
 * A person on the map (also a gunner on a static weapon, which the game draws like a walking soldier): the soldier glyph, a dot whose black tip
 * points the way he faces; a squad leader is the heading arrow under his number disc (see below), a commander's star disc replaces the dot; the selected
 * player's squad (himself included) is green, and only the selected player shows the view cone.
 */
function drawPerson(p, tick, x, y, heading, col, alpha, sel, ik, sp) {
  const own = ownSquad(p, tick), colour = own ? SQUAD : col, leader = p && isLeader(p, tick);
  if (sel && heading >= 0) viewCone(x, y, heading, ik);
  if (leader) {
    // a squad leader is the heading arrow (32 px, its black triangle points ahead) under the number disc, both centred on the soldier and
    // turned with him: only the triangle shows beyond the disc, and the head of the "1" points the way he faces
    const key = squadIconKey(squadOf(p, tick));
    drawSprite(ICON.arrow, "#ffffff", nativeSize(ICON.arrow) * ik, x, y, heading, alpha);
    drawSprite(key, colour, nativeSize(key) * ik, x, y, heading, alpha);
  } else if (!(p && isCommander(p, tick)) && !drawSprite(ICON.soldier, colour, sp, x, y, heading, alpha)) fallbackDot(x, y, sp * 0.35, colour, alpha);
  if (p && isCommander(p, tick)) {
    const key = teamOfPlayer(p, tick) === S.persp ? ICON.commanderFriend : ICON.commanderEnemy;
    drawSprite(ICON.arrow, "#ffffff", nativeSize(ICON.arrow) * ik, x, y, heading, alpha);       // the commander too: arrow under the star disc, only its tip shows
    drawSprite(key, "#ffffff", nativeSize(key) * ik, x, y, -1, alpha);
  }
}

/**
 * Commander / squad leader inside a vehicle: the game overlays a 16 x 64 texture (`mini_Commander<Size>`, `mini_Squad<Size>_<n>`; Size is the
 * vehicle's `miniMapIconLeaderSize`) rotated with the vehicle; its star or number lies behind the vehicle centre, further back for bigger sizes.
 */
function leaderOverlay(tr, crew, tick, x, y, heading, ik, colour) {
  const { ctx } = V, info = vehicleInfo(tr.tpl), size = ((info && info.size) || "Medium").toLowerCase();
  for (const pid of crew) {
    const p = M.players.get(pid); if (!p) continue;
    const key = isCommander(p, tick) ? "ingame/vehicles/icons/minimap/mini_commander" + size
      : isLeader(p, tick) ? "ingame/vehicles/icons/minimap/mini_squad" + size + "_" + Math.min(9, squadOf(p, tick)) : null;
    if (!key) continue;
    // the number takes the vehicle's colour (the atlas holds a white digit with a dark edge: multiplied by the colour); the commander star stays yellow
    const tint = isCommander(p, tick) ? "#ffffff" : colour, w = 16 * ik, h = 64 * ik, spr = spriteRect(key, tint, w * V.dpr, h * V.dpr);
    if (!spr) continue;
    ctx.save(); ctx.translate(x, y); if (heading >= 0) ctx.rotate((heading * Math.PI) / 180);
    ctx.drawImage(spr, -w / 2, -h / 2, w, h); ctx.restore();
  }
}

/** The selected soldier's view direction: the game's own `mini_LocalArrow2` texture (a white V with arcs, apex at the bottom), rotated. */
function viewCone(x, y, heading, ik) {
  const { ctx } = V, img = plain(ICON.localArrow);
  if (!img) return;
  ctx.save(); ctx.translate(x, y); ctx.rotate((heading * Math.PI) / 180);
  ctx.globalAlpha = 0.95; ctx.drawImage(img, -img.width * ik / 2, -img.height * ik / 2, img.width * ik, img.height * ik); ctx.restore();   // the V's apex is the texture centre
}

/** Members of the selected player's squad are drawn green, as in the game (squad colour table 0, 1, 0). */
function ownSquad(p, tick) {
  if (!p || S.sel == null) return false;
  const me = M.players.get(S.sel);
  if (!me) return false;
  const sq = squadOf(p, tick);
  return sq > 0 && sq === squadOf(me, tick) && teamOfPlayer(me, tick) === teamOfPlayer(p, tick);
}

/**
 * Artillery and air strikes (BF2.exe FUN_0077f8e0): the game's red target ring `placedAirstrike` (58 px texture, pulsing) around the strike
 * area and the 15 px `icon_artillery` glyph on it; shown while shells / bombs are in the air and a few seconds after.
 */
const STRIKE_RADIUS = 45, STRIKE_AFTER = 4 * TPS;
function drawStrikes(tick, k) {
  const { ctx } = V, ring = plain(ICON.airstrike), ik = (Math.min(V.W, V.H) / 512) * S.iconScale;
  for (const s of M.doc.strikes || []) {
    if (tick < s.t0 || tick > s.t1 + STRIKE_AFTER) continue;
    const x = w2sx(s.x), y = w2sy(s.z);
    if (x < -80 || y < -80 || x > V.W + 80 || y > V.H + 80) continue;
    const fade = tick > s.t1 ? 1 - (tick - s.t1) / STRIKE_AFTER : 1, pulse = 0.88 + 0.12 * Math.sin((tick / TPS) * 5), d = Math.max(58 * ik * 0.6, 2 * STRIKE_RADIUS * k) * pulse;
    ctx.globalAlpha = fade;
    if (ring) ctx.drawImage(ring, x - d / 2, y - d / 2, d, d);
    const key = ICON.artillery;
    drawSprite(key, "#ffffff", nativeSize(key) * ik, x, y, -1, 1);                     // the glyph as stored: white with a black outline
    ctx.globalAlpha = 1;
  }
}

/**
 * A UAV as the game's 2D map shows it (BF2.exe FUN_0077fc30 / FUN_0077b280): the gold quarter-disc texture `map_UAV` (150 x 150, apex at the
 * image centre) drawn 2 x 100 world units wide and rotated about the UAV by `angle += dt * 4.0` (radians, wrapped at 2 pi) - counter-clockwise on
 * screen (measured on the game video); the white `icon_UAV` plane stays fixed at the centre.
 */
const UAV_SWEEP_RADIUS = 100, UAV_SPEED = 4.0;
function drawUav(tr, tick, k, px) {
  const { ctx } = V, x = w2sx(tr.cx), y = w2sy(tr.cz), r = UAV_SWEEP_RADIUS * k;
  if (x < -r || y < -r || x > V.W + r || y > V.H + r) return;
  const sweep = plain(ICON.uavSweep);
  if (sweep) {
    FRAME.animating = true;                                               // the sweep turns in real time, not game time
    ctx.save(); ctx.translate(x, y); ctx.rotate(-((performance.now() / 1000) * UAV_SPEED) % (2 * Math.PI));
    ctx.globalAlpha = 0.9; ctx.drawImage(sweep, -r, -r, 2 * r, 2 * r); ctx.restore();
  }
  const key = ICON.uavIcon;
  drawSprite(key, "#ffffff", nativeSize(key) * (Math.min(V.W, V.H) / 512) * S.iconScale, x, y, -1, 1);
  hit(x, y, Math.max(px * 0.7, 9), tr);
}

function hit(x, y, r, tr) { if (HIT.n < HIT.x.length) { const i = HIT.n++; HIT.x[i] = x; HIT.y[i] = y; HIT.r[i] = r; HIT.tr[i] = tr; } }
function ring(x, y, r) { const { ctx } = V; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.3); ctx.stroke(); }
function drawDeath(x, y) { const { ctx } = V; ctx.strokeStyle = "rgba(255,255,255,.75)"; ctx.lineWidth = 1.8; ctx.beginPath(); ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4); ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4); ctx.stroke(); }
function fallbackDot(x, y, r, col, alpha) { const { ctx } = V; ctx.globalAlpha = alpha; ctx.fillStyle = col; ctx.strokeStyle = "#0b0f14"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.3); ctx.fill(); ctx.stroke(); ctx.globalAlpha = 1; }
function fallbackTri(x, y, s, col, h, alpha) {
  const { ctx } = V; ctx.save(); ctx.globalAlpha = alpha; ctx.translate(x, y); if (h >= 0) ctx.rotate((h * Math.PI) / 180);
  ctx.fillStyle = col; ctx.strokeStyle = "#0b0f14"; ctx.lineWidth = 1.2; ctx.beginPath();
  ctx.moveTo(0, -s); ctx.lineTo(s * 0.8, s * 0.8); ctx.lineTo(0, s * 0.35); ctx.lineTo(-s * 0.8, s * 0.8); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
}

/** Nearest unit under a screen point (hit targets of the last frame), or null. */
export function pick(mx, my, minRadius = 9) {          // a finger needs a bigger target than a mouse pointer
  let best = null, bd = Infinity;
  for (let i = 0; i < HIT.n; i++) {
    const d = (HIT.x[i] - mx) ** 2 + (HIT.y[i] - my) ** 2, r = Math.max(HIT.r[i], minRadius);
    if (d <= r * r && d < bd) { bd = d; best = HIT.tr[i]; }
  }
  return best;
}