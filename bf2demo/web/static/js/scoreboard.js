// The game's scoreboard (HudElementsScoreboard.con, 800 x 600 layout, the game's textures and bitmap fonts) drawn for any moment of the recording.
// Columns are the game's score icons: score, teamwork score, kills, deaths (the ping column is not recorded). Own side on the left.
// Geometry comes from the .con (list nodes `10 75 389 462 19 1` and `401 75 ...`: row height 19 + 1 gap, border top 20 / bottom 22 / sides 3);
// the cells and colours were measured on a 1 : 1 screenshot of the game's own scoreboard.
import { A, kitIcon, plain, sprite, vehicleIconKey, vehicleInfo } from "./assets.js";
import { dpr, hudK } from "./hudscale.js";
import { drawIn, drawText, hasFont, textWidth } from "./font.js";
import { M, isPresent, kitOf, rankOf, roundAt, seatOf, squadOf, statsAt, teamOfPlayer } from "./model.js";
import { S } from "./state.js";
import { $, TPS, fmtTime, prettyMap } from "./util.js";

const BOLD = "hudFontLocalBold_9", BOLD2 = "hudFontBold_9", LIST = "scoreboardFontLocal_8";
const GOLD = "#CBCB97", YELLOW = "#FFCA0B", EDGE = "#7B7963", LIST_BG = "rgba(190,186,148,0.9)", SCROLL_BG = "#939273";
const ROW = 20, ROW_H = 19, LIST_Y = 75, TOP = 95, VISIBLE = 21;
const FRIEND_TEXT = "#1B69F2", ENEMY_TEXT = "#FC0610", DEAD_TEXT = "#4F4F35", SELECT_ROW = "#D8BB6D", GLYPH = "#58533A", FRAME = "#939370";
const FLAG = { US: "us", CH: "ch", MEC: "mec", EU: "eu" };
const ICONS = {
  death: "ingame/scoreboard/icons/icon_death", unknown: "ingame/scoreboard/icons/icon_faded",
  rank: (n) => "ingame/generalicons/ranks/rank_" + String(n).padStart(2, "0"),
};
const ui = { open: false, scroll: { 1: 0, 2: 0 }, hits: [], cb: null, scale: 1, ox: 0, oy: 0 };

export const isOpen = () => ui.open;
export function initScoreboard(callbacks) {
  ui.cb = callbacks;
  const cv = $("sb");
  cv.onclick = (e) => {
    const r = cv.getBoundingClientRect(), x = ((e.clientX - r.left) * dpr() - ui.ox) / ui.scale, y = ((e.clientY - r.top) * dpr() - ui.oy) / ui.scale;
    const hit = ui.hits.find((h) => x >= h.x && x < h.x + h.w && y >= h.y && y < h.y + h.h);
    if (!hit) { if (x < 0 || y < 0 || x > 800 || y > 600) setOpen(false); return; }
    if (hit.player != null) { ui.cb.select(hit.player, true); setOpen(false); }
  };
  cv.onwheel = (e) => {
    e.preventDefault();
    const r = cv.getBoundingClientRect(), x = ((e.clientX - r.left) * dpr() - ui.ox) / ui.scale, team = x < 400 ? S.persp : 3 - S.persp;
    ui.scroll[team] = Math.max(0, ui.scroll[team] + Math.sign(e.deltaY) * 3);
    draw();
  };
  $("btnBoard").onclick = () => setOpen(!ui.open);
}
export function setOpen(on) { ui.open = on; $("sb").hidden = !on; $("btnBoard").classList.toggle("on", on); if (on) draw(); }

const str = (key, fallback) => A.strings[key] || fallback;

function rowsFor(team, tick) {
  const out = [];
  for (const p of M.doc.players) {
    if (!isPresent(p, tick) || teamOfPlayer(p, tick) !== team) continue;
    out.push({ p, ...statsAt(p, tick), squad: squadOf(p, tick), kit: kitOf(p, tick), rank: rankOf(p, tick) });
  }
  out.sort((a, b) => b.score - a.score || b.kills - a.kills || a.deaths - b.deaths);
  return out;
}

/** `text` shortened with ".." until it fits `max` font pixels. */
function fit(font, text, max) {
  if (textWidth(font, text) <= max) return text;
  while (text.length > 1 && textWidth(font, text + "..") > max) text = text.slice(0, -1);
  return text + "..";
}

// value columns sit under the icons of `scoreboard_icons` (150 x 20, five icons): their centres in the strip, measured on the texture and on
// the game's screenshot (the same on both sides); the fifth column is the ping, which a recording does not hold
const COL_CX = [7, 39, 70.5, 103, 136], STRIP_X = 221;

const alive = (p, tick) => !!seatOf(p.player_id, tick) || (M.byOwner.get(p.player_id) || []).some((tr) => tick >= tr.t0 && tick <= tr.tEnd);

// the game's list text carries about 0.74 of the ink of the font atlas (measured: coverage of "J. Stenkvist" on its screenshot 141 against 192 for the
// atlas glyphs), so it is drawn a little lighter than the opaque atlas
const LIST_INK = 0.75;
function listText(g, text, x, y, color) { g.globalAlpha = LIST_INK; drawText(g, LIST, text, x, y, color, 1, false); g.globalAlpha = 1; }

function numbers(g, values, x0, y, color) {
  values.forEach((v, c) => { const s = String(v); listText(g, s, x0 + STRIP_X + COL_CX[c] - textWidth(LIST, s) / 2, y, color); });
}

/** A 1 px outlined cell of a row (kit, rank). */
function cell(g, x, y, w, h) { g.strokeStyle = FRAME; g.lineWidth = 1; g.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1); }

function panel(g, team, left, tick) {
  const x0 = left ? 10 : 401, rows = rowsFor(team, tick), hits = ui.hits;
  const tab = plain(left ? "ingame/scoreboard/team1_byscore" : "ingame/scoreboard/team2_empty");
  if (tab) g.drawImage(tab, x0, 26);
  // flag (FriendlyFlag 17,33 / EnemyFlag 406,33, 18 x 12) and "ROUNDS WON n": the label is right aligned in its node (66..216 / 463..613), the number
  // starts at 220 / 616; the team name node stays empty in the game's screenshot, so no name is drawn
  const code = (M.doc.team_names && M.doc.team_names[team]) || "";
  const flag = plain("ingame/flags/icons/hud/score/" + (FLAG[code] || "us") + "/scoreboard_flag");
  if (flag) g.drawImage(flag, left ? 17 : 406, 33, 18, 12);
  drawIn(g, BOLD, str("hud_text_menu_score_roundswon", "ROUNDS WON"), left ? 66 : 463, 30, 150, "right", GOLD, 1, false);
  drawText(g, BOLD2, "0", left ? 220 : 616, 30, GOLD, 1, false);
  if (left) drawIn(g, BOLD, str("hud_text_menu_score_players", "PLAYERS"), 12, 53, 120, "center", "#FFFFFF", 1, false);     // the one tab a replay has
  // the list: border colour all round (20 px header strip, 22 px footer, 3 px sides), the translucent paper inside
  g.fillStyle = EDGE; g.fillRect(x0, LIST_Y, 389, 462);
  g.fillStyle = LIST_BG; g.fillRect(x0 + 3, TOP, 383, 420);
  const icons = plain("ingame/scoreboard/scoreboard_icons");
  if (icons) g.drawImage(icons, 0, 0, 150, 20, x0 + STRIP_X, 74, 150, 20);          // score, teamwork, kills, deaths, ping
  drawText(g, BOLD, str("hud_text_menu_score_playername", "PLAYER NAME"), x0 + 5, 75, GOLD, 1, false);
  const bottom = plain("ingame/scoreboard/bottom"); if (bottom) g.drawImage(bottom, x0, 536);

  // rows
  const lines = rows;
  const maxScroll = Math.max(0, lines.length - VISIBLE);
  ui.scroll[team] = Math.min(ui.scroll[team], maxScroll);
  const start = ui.scroll[team];
  g.save(); g.beginPath(); g.rect(x0 + 3, TOP, 383, 420); g.clip();
  for (let i = 0; i < VISIBLE && start + i < lines.length; i++) {
    const r = lines[start + i], y = TOP + i * ROW;
    const p = r.p, selected = S.sel === p.player_id, dead = !alive(p, tick);
    if (selected) { g.fillStyle = SELECT_ROW; g.fillRect(x0 + 3, y, 383, ROW_H); }
    // cell 1: the kit glyph in dark olive (the skull when dead, "?" when the kit is unknown); cell 2: the rank insignia
    cell(g, x0 + 5, y + 3, 15, 15); cell(g, x0 + 26, y + 3, 16, 15);
    // the glyph of cell 1: the minimap icon of the vehicle the player sits in, else his kit's, the skull when dead
    const seat = seatOf(p.player_id, tick), info = seat && seat.track ? vehicleInfo(seat.track.tpl) : null;
    const kitName = r.kit != null ? M.kitNames[r.kit] : null;
    const icon = dead ? ICONS.death : info && info.icon ? vehicleIconKey(seat.track.tpl) : kitName ? kitIcon(kitName) : ICONS.unknown;
    const glyph = icon && sprite(icon, GLYPH, 13); if (glyph) g.drawImage(glyph, x0 + 6, y + 4, 13, 13);
    const insignia = r.rank != null && r.rank >= 0 ? plain(ICONS.rank(r.rank)) : null; if (insignia) g.drawImage(insignia, x0 + 26, y + 3, 16, 16);
    const color = dead ? DEAD_TEXT : team === S.persp ? FRIEND_TEXT : ENEMY_TEXT;
    listText(g, fit(LIST, p.name.trim(), 172), x0 + 44, y + 2, color);
    numbers(g, [r.score, r.teamwork, r.kills, r.deaths], x0, y + 2, color);
    hits.push({ x: x0 + 3, y, w: 383, h: ROW_H, player: p.player_id });
  }
  g.restore();
  if (maxScroll > 0) {                                           // the game's scroll bar (width 10, inside the right border)
    g.fillStyle = SCROLL_BG; g.fillRect(x0 + 376, TOP, 10, 420);
    const th = Math.max(16, (VISIBLE / lines.length) * 420);
    g.fillStyle = "#7c7b63"; g.fillRect(x0 + 376, TOP + (start / maxScroll) * (420 - th), 10, th);
  }
  // the totals row sits on the footer border: "TOTAL PLAYERS: n" and the column sums
  const tot = rows.reduce((a, r) => ({ s: a.s + r.score, t: a.t + r.teamwork, k: a.k + r.kills, d: a.d + r.deaths }), { s: 0, t: 0, k: 0, d: 0 });
  listText(g, "TOTAL PLAYERS: " + rows.length, x0 + 5, 519, GOLD);
  numbers(g, [tot.s, tot.t, tot.k, tot.d], x0, 519, GOLD);
}

function draw() {
  if (!ui.open || !M) return;
  const cv = $("sb"), wrap = $("mapWrap").getBoundingClientRect(), ratio = dpr();
  const dw = Math.round(wrap.width * ratio), dh = Math.round(wrap.height * ratio);
  if (cv.width !== dw || cv.height !== dh) { cv.width = dw; cv.height = dh; }
  const g = cv.getContext("2d");
  ui.scale = hudK(wrap.width, wrap.height);                       // the game fits its 800 x 600 layout to the screen; so does the page
  ui.ox = Math.floor((dw - 800 * ui.scale) / 2); ui.oy = Math.floor((dh - 600 * ui.scale) / 2);
  g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, cv.width, cv.height);        // no veil: the game does not dim its world behind the scoreboard
  g.setTransform(ui.scale, 0, 0, ui.scale, ui.ox, ui.oy); g.imageSmoothingEnabled = ui.scale !== 1; g.imageSmoothingQuality = "high";
  ui.hits = [];
  if (!hasFont(BOLD)) { g.fillStyle = "#fff"; g.font = "16px sans-serif"; g.fillText("Fonts are not available (build the asset store from the game install).", 20, 40); return; }
  const tick = S.tick | 0;
  panel(g, S.persp, true, tick); panel(g, 3 - S.persp, false, tick);
  // the bottom info bar: map, time left, players (the game prints "Right click to activate mouse" here, of no use in a replay)
  const bar = plain("ingame/scoreboard/staticinfobackground"); if (bar) g.drawImage(bar, 10, 540, 780, 18);
  const round = roundAt(tick), left = round.end > 0 ? Math.max(0, (round.end - tick) / TPS) : null;
  const present = M.doc.players.filter((p) => isPresent(p, tick)).length;
  const info = `${prettyMap(M.doc.demo.map).toUpperCase()}   |   ${left != null ? "TIME LEFT " + fmtTime(left) : "TIME " + fmtTime((tick - round.start) / TPS)}   |   ${present} PLAYERS`;
  drawIn(g, BOLD, info, 10, 543, 780, "center", GOLD, 1, false);                    // HelpText node: 780 wide, centred
}

/** Refresh while open (called with the HUD, 4 Hz). */
export function updateScoreboard() { if (ui.open) draw(); }
export function redrawScoreboard() { draw(); }
