// Side panels and map overlays: kill feed, log, scoreboard, player page, round info, filter drawer and legend.
import { A, ICON, iconUrl, kitIcon } from "./assets.js";
import { buildClip } from "./clipui.js";
import { buildMoments } from "./moments.js";
import { drawHudBar } from "./hudbar.js";
import { killHTML, killNode } from "./killfeed.js";
import { redrawScoreboard, updateScoreboard } from "./scoreboard.js";
import { vehicleLabel } from "./text.js";
import { T } from "./i18n.js";
import { loadHd } from "./mapview.js";
import { M, heldWeapon, seatOf, teamName } from "./model.js";
import { KIT_COL, TEAM_COL, setPerspective } from "./palette.js";
import { S, invalidate } from "./state.js";
import { dropTimelineCache } from "./timeline.js";
import { $, TPS, bsearch, clamp, el, esc, fmtTime, prettyMap } from "./util.js";

const ui = { feedNodes: new Map(), sort: ["score", -1], feedKinds: {}, feedQ: "", pQ: "", rows: [], lastNow: -2, lastKillSig: "", cb: null };

export function initPanels(callbacks) {
  ui.cb = callbacks;
  document.querySelectorAll(".tabs button").forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });
  $("pSearch").oninput = (e) => { ui.pQ = e.target.value.toLowerCase(); renderBoard(); };
  $("feedSearch").oninput = (e) => { ui.feedQ = e.target.value.toLowerCase(); renderLog(); };
  $("btnFilters").onclick = () => toggleDrawer("drawerFilters");
  $("btnClip").onclick = () => toggleDrawer("drawerClip");
}
function toggleDrawer(id) {
  for (const d of ["drawerFilters", "drawerClip"]) $(d).hidden = d === id ? !$(d).hidden : true;
}
export function showTab(tab) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tabbody").forEach((b) => { b.hidden = b.dataset.tab !== tab; });
}

export function buildPanels() {
  ui.feedNodes.clear(); $("killfeed").innerHTML = "";
  buildFilters(); buildLegend(); buildClip(); buildMoments(); buildLogKinds(); renderLog(); renderBoard(); renderPlayerPanel();
  $("pSearch").value = ""; ui.pQ = ""; $("feedSearch").value = ""; ui.feedQ = "";
}

// ----------------------------------------------------------------------------------------------------- kit icons
function kitImg(kit, cls = "kit") {
  const name = M.kitNames[kit]; const key = name && kitIcon(name);
  return key ? `<img class="${cls}" src="${iconUrl(key)}" alt="${esc(name)}" title="${esc(name)}">` : "";
}
const dot = (col) => `<i class="dot" style="background:${col}"></i>`;

// ------------------------------------------------------------------------------------------------------- drawers
function chip(parent, label, color, on, cb) {
  const c = el("span", "chip" + (on ? " on" : ""), (color ? dot(color) : "") + esc(label));
  c.style.color = color || "inherit";
  c.onclick = () => { const v = !c.classList.contains("on"); c.classList.toggle("on", v); cb(v); invalidate(); };
  parent.append(c); return c;
}
function checkbox(parent, label, get, set) {
  const row = el("label", "check", `<input type="checkbox"><span>${esc(label)}</span>`);
  const box = row.firstChild; box.checked = get();
  box.onchange = () => { set(box.checked); invalidate(); };
  parent.append(row);
}
/** A square toggle with the game's icon above a short word: the basic filters are these five buttons and the two teams. */
function iconButton(parent, key, glyph, label, get, set) {
  const b = el("button", "ibtn" + (get() ? " on" : ""), `<span class="lg">${key ? `<img src="${iconUrl(key)}" alt="">` : esc(glyph)}</span><small>${esc(label)}</small>`);
  b.title = label;
  b.onclick = () => { const v = !b.classList.contains("on"); b.classList.toggle("on", v); set(v); invalidate(); };
  parent.append(b);
}

function buildFilters() {
  const root = $("filtersBody"); root.innerHTML = "";
  const L = S.layers, row = (cls = "chips") => { const d = el("div", cls); root.append(d); return d; };
  const teams = row();
  for (const t of [1, 2]) chip(teams, teamName(t), TEAM_COL[t], S.teams[t] !== false, (v) => { S.teams[t] = v; });
  const show = row("ibtns");
  iconButton(show, ICON.arrow, "", T("f_soldiers"), () => S.kinds.soldier, (v) => { S.kinds.soldier = v; });
  iconButton(show, "ingame/vehicles/icons/minimap/mini_tank", "", T("f_vehicles"), () => S.kinds.vehicle, (v) => { S.kinds.vehicle = v; });
  iconButton(show, "ingame/vehicles/icons/minimap/mini_jeep", "", T("f_empty"), () => S.kinds.empty, (v) => { S.kinds.empty = v; });
  iconButton(show, "ingame/flags/icons/minimap/us/minimap_cp", "⚑", T("f_flags"), () => L.cps, (v) => { L.cps = v; });
  iconButton(show, ICON.uav, "", T("f_uav"), () => S.kinds.other, (v) => { S.kinds.other = v; });
  iconButton(show, ICON.artillery, "", T("f_strikes"), () => L.strikes, (v) => { L.strikes = v; });
  iconButton(show, null, "Aa", T("f_names"), () => L.names, (v) => { L.names = v; });

  const more = el("details", "more"); more.append(el("summary", null, esc(T("more"))));
  const sec = (title) => { more.append(el("h4", null, esc(T(title)))); const d = el("div", "chips"); more.append(d); return d; };
  more.append(el("h4", null, esc(T("l_persp"))));
  const persp = el("select");                                         // which side wears the game's blue (friendly) colour
  persp.innerHTML = [1, 2].map((t) => `<option value="${t}">${esc(teamName(t))} ${esc(T("c_blue"))} / ${esc(teamName(3 - t))} ${esc(T("c_red"))}</option>`).join("");
  persp.value = String(S.persp); persp.onchange = () => { S.persp = +persp.value; setPerspective(S.persp); dropTimelineCache(); buildPanels(); invalidate(); };
  more.append(persp);
  more.append(el("h4", null, esc(T("l_hudsize"))));
  const hud = el("select"); hud.innerHTML = [0, 1, 1.5, 2, 3].map((k) => `<option value="${k}">${esc(k ? k + "x" : T("auto"))}</option>`).join("");
  hud.value = String(S.hudScale); hud.onchange = () => { S.hudScale = +hud.value; resetKillFeed(); updateHud(S.tick | 0, S.playing, S.speed); redrawScoreboard(); }; more.append(hud);
  more.append(el("h4", null, esc(T("l_iconsize"))));
  const size = el("input"); size.type = "range"; size.min = "0.5"; size.max = "2"; size.step = "0.1"; size.value = String(S.iconScale);
  size.oninput = () => { S.iconScale = +size.value; invalidate(); }; more.append(size);
  more.append(el("h4", null, esc(T("l_rate"))));
  const rate = el("input"); rate.type = "number"; rate.min = "0.5"; rate.max = "1.5"; rate.step = "0.001"; rate.value = String(S.rate);
  rate.title = T("l_rate_tip"); rate.onchange = () => { S.rate = clamp(+rate.value || 1, 0.5, 1.5); ui.cb.rate(); }; more.append(rate);
  checkbox(more, T("l_hd"), () => L.hd, (v) => { L.hd = v; if (v && M) loadHd(M.doc.demo.map); });
  const kits = sec("kits");
  M.kitNames.forEach((n, i) => { const c = chip(kits, n, KIT_COL[i], S.kits[i] !== false, (v) => { S.kits[i] = v; }); c.insertAdjacentHTML("afterbegin", kitImg(i)); });
  more.append(el("h4", null, esc(T("squad"))));
  const squads = new Set(); for (const p of M.doc.players) for (const [, sq] of p.squad_history || []) if (sq > 0) squads.add(sq);
  const sel = el("select"); sel.innerHTML = `<option value="all">${esc(T("any_squad"))}</option><option value="none">${esc(T("no_squad"))}</option>` +
    [...squads].sort((a, b) => a - b).map((sq) => `<option value="${sq}">#${sq}</option>`).join("");
  sel.value = S.squad; sel.onchange = () => { S.squad = sel.value; invalidate(); }; more.append(sel);
  more.append(el("h4", null, esc(T("color_by"))));
  const col = el("select"); col.innerHTML = ["team", "squad", "kit"].map((k) => `<option value="${k}">${esc(T("c_" + k))}</option>`).join("");
  col.value = S.color; col.onchange = () => { S.color = col.value; invalidate(); }; more.append(col);
  more.append(el("h4", null, esc(T("layers"))));
  checkbox(more, T("l_trail"), () => L.trail, (v) => { L.trail = v; });
  checkbox(more, T("l_corpses"), () => L.corpses, (v) => { L.corpses = v; });
  checkbox(more, T("l_lines"), () => L.lines, (v) => { L.lines = v; });
  checkbox(more, T("l_heat"), () => L.heat, (v) => { L.heat = v; });
  root.append(more);
  if (!A.installed) root.append(el("div", "note", esc(T("no_backdrop"))));
}

function buildLegend() {
  const img = (key, col) => `<span class="lg" style="--c:${col}"><img src="${iconUrl(key)}" alt=""></span>`;
  const rows = [
    [img(ICON.soldier, TEAM_COL[1]), T("lg_soldier")],
    [`<span class="lg"><b>3</b></span>`, T("lg_leader")],
    [`<i class="dot" style="background:${TEAM_COL[1]}"></i><i class="dot" style="background:${TEAM_COL[2]}"></i>`, T("lg_squadmate")],
    [img("ingame/vehicles/icons/minimap/mini_tank", TEAM_COL[2]) + img("ingame/vehicles/icons/minimap/mini_attack_heli", TEAM_COL[2]) + img("ingame/vehicles/icons/minimap/mini_jet", TEAM_COL[2]), T("lg_vehicle")],
    [img("ingame/vehicles/icons/minimap/mini_jeep", "#e6e9ee"), T("lg_empty")],
    [img(ICON.artillery, "#ffcf70"), T("lg_strike")],
    [`<span class="lg"><img src="${iconUrl("ingame/flags/icons/minimap/us/minimap_cp")}" alt=""></span>`, T("lg_flag")],
    [`<span class="lg">✕</span>`, T("lg_dead")],
    [img(ICON.soldier, "#ffffff66"), T("lg_gap")],
    [img(ICON.uav, "#fff"), T("lg_uav")],
  ];
  $("legendBody").innerHTML = rows.map(([icon, text]) => `<div class="lrow">${icon}<span>${esc(text)}</span></div>`).join("") + `<div class="note">${esc(T("free_look"))}</div>`;
}

// ----------------------------------------------------------------------------------------------------- kill feed
export function lineHTML(f) {
  const k = M.logOf.get(f);
  return k ? killHTML(k) : esc(f.display || f.text);
}

/** Forget the drawn kill lines (they are canvases at a fixed size: redo them after a resize or a HUD size change). */
export function resetKillFeed() { ui.feedNodes.clear(); $("killfeed").innerHTML = ""; }

const MAX_LINES = 5, LIFE_SECONDS = 14, FADE_SECONDS = 1.5;

/**
 * The game's kill messages: top-left, at most five lines, newest at the bottom, in the game's bitmap font and colours (killfeed.js). A line stays
 * fully visible for its whole life and only fades in the last moments; the DOM lines are reused (never rebuilt), so nothing flickers.
 * Life is measured in real seconds: game time divided by the playback speed.
 */
export function updateKillFeed(tick, playing, speed) {
  const box = $("killfeed"), rate = playing ? Math.max(1, speed) : 1, window = LIFE_SECONDS * TPS * rate, fade = FADE_SECONDS * TPS * rate;
  const wanted = [];
  for (let i = bsearch(M.logTicks, tick); i >= 0 && wanted.length < MAX_LINES; i--) {
    if (tick - M.logKills[i].tick > window) break;
    wanted.unshift(i);
  }
  for (const [i, node] of ui.feedNodes) if (!wanted.includes(i)) { node.remove(); ui.feedNodes.delete(i); }
  let previous = null;
  for (const i of wanted) {
    const k = M.logKills[i];
    let node = ui.feedNodes.get(i);
    if (!node) {
      node = killNode(k);
      ui.feedNodes.set(i, node);
      box.insertBefore(node, previous ? previous.nextSibling : box.firstChild);
    }
    const left = window - (tick - k.tick);
    node.style.opacity = left >= fade ? "1" : Math.max(0.05, left / fade).toFixed(2);
    previous = node;
  }
}

// ----------------------------------------------------------------------------------------------------------- log
function buildLogKinds() {
  const counts = {}; for (const f of M.feed) counts[f.kind] = (counts[f.kind] || 0) + 1;
  const hidden = new Set(["vehicle", "spot", "call", "uav", "spawn", "assist", "capture-initial", "neutralize", "tickets"]);
  ui.feedKinds = {}; const box = $("feedKinds"); box.innerHTML = "";
  for (const k of Object.keys(counts).sort((a, b) => counts[b] - counts[a])) {
    ui.feedKinds[k] = !hidden.has(k);
    chip(box, `${T('k_' + k)} ${counts[k]}`, null, ui.feedKinds[k], (v) => { ui.feedKinds[k] = v; renderLog(); });
  }
}
function renderLog() {
  const q = ui.feedQ, box = $("feedList"); box.innerHTML = "";
  ui.rows = M.feed.filter((f) => ui.feedKinds[f.kind] && (!q || (f.display || f.text).toLowerCase().includes(q)));
  ui.rowTicks = ui.rows.map((f) => f.tick);
  const MAX = 2500, shown = ui.rows.length > MAX ? ui.rows.slice(0, MAX) : ui.rows, frag = document.createDocumentFragment();
  shown.forEach((f) => {
    const row = el("div", "fl", `<span class="ts">${fmtTime((f.tick - M.tMin) / TPS)}</span><span class="k">${esc(T("k_" + f.kind))}</span><span>${lineHTML(f)}</span>`);
    row.onclick = () => ui.cb.seek(Math.max(M.tMin, f.tick - 2 * TPS));
    frag.append(row);
  });
  box.append(frag);
  if (ui.rows.length > MAX) box.append(el("div", "muted", `+${ui.rows.length - MAX}`));
  ui.lastNow = -2;
}
function markLogNow(playing) {
  const rows = $("feedList").children, i = Math.min(bsearch(ui.rowTicks || [], S.tick | 0), rows.length - 1);
  if (i === ui.lastNow) return;
  if (rows[ui.lastNow]) rows[ui.lastNow].classList.remove("now");
  ui.lastNow = i;
  if (i >= 0 && rows[i]) { rows[i].classList.add("now"); if (playing && !$("right").matches(":hover")) rows[i].scrollIntoView({ block: "nearest" }); }
}

// ------------------------------------------------------------------------------------------------------ scoreboard
/** The player finder (Player tab): everybody of the recording with the final numbers; the live scoreboard is the Scoreboard button. */
export function renderBoard() {
  const [key, dir] = ui.sort, q = ui.pQ;
  const val = (r) => (key === "kd" ? r.kills / Math.max(1, r.deaths) : key === "name" ? r.name.toLowerCase() : r[key] || 0);
  const rows = M.doc.scoreboard.filter((r) => !q || r.name.toLowerCase().includes(q));
  rows.sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * dir * -1);
  const th = (k, l) => `<th data-k="${k}">${esc(T(l))}${key === k ? (dir < 0 ? " ▾" : " ▴") : ""}</th>`;
  let html = `<table class="t"><tr><th></th>${th("name", "name")}${th("score", "score")}${th("kills", "kills")}${th("deaths", "deaths")}</tr>`;
  for (const r of rows) {
    html += `<tr class="row ${S.sel === r.player_id ? "sel" : ""}" data-p="${r.player_id}"><td>${kitImg(r.kit)}</td><td>${dot(TEAM_COL[r.team] || TEAM_COL[0])}${esc(r.name)}</td>` +
      `<td class="num">${r.score}</td><td class="num">${r.kills}</td><td class="num">${r.deaths}</td></tr>`;
  }
  const box = $("board"); box.innerHTML = html + "</table>";
  box.querySelectorAll("th[data-k]").forEach((h) => { h.onclick = () => { ui.sort = [h.dataset.k, ui.sort[0] === h.dataset.k ? -ui.sort[1] : -1]; renderBoard(); }; });
  box.querySelectorAll("tr.row").forEach((r) => { r.onclick = () => ui.cb.select(+r.dataset.p, true); });
}

// ------------------------------------------------------------------------------------------------------ player page
export function renderPlayerPanel() {
  const box = $("playerPanel"), p = S.sel != null ? M.players.get(S.sel) : null;
  if (!p) { box.innerHTML = `<div class="muted">${esc(T("pick_player"))}</div>`; return; }
  const sb = M.doc.scoreboard.find((r) => r.player_id === p.player_id) || {};
  const mine = M.kills.filter((k) => k.k === p.player_id && k.v !== p.player_id), deaths = M.kills.filter((k) => k.v === p.player_id);
  let dist = 0; const veh = new Map();
  for (const tr of M.byOwner.get(p.player_id) || []) for (let i = 1; i < tr.t.length; i++) { const d = Math.hypot(tr.x[i] - tr.x[i - 1], tr.z[i] - tr.z[i - 1]); if (d < 120 && tr.t[i] - tr.t[i - 1] < 90) dist += d; }
  for (const s of M.seatsOf.get(p.player_id) || []) { if (s.track.parachute) continue; const n = vehicleLabel(s.track.tpl); veh.set(n, (veh.get(n) || 0) + 1); }
  const kitsUsed = [...new Set((p.kit_history || []).map(([, k]) => k))].map((k) => kitImg(k) + esc(M.kitNames[k] || "")).join(" ");
  let html = `<h3>${dot(TEAM_COL[p.team] || TEAM_COL[0])}${esc(p.name)}</h3><div class="muted">${esc(teamName(p.team))}${p.is_ai ? " · bot" : ""}${p.kicked ? " · " + esc(T("kicked")) : ""}</div>` +
    `<div class="statgrid"><div class="stat"><b>${mine.length}</b><span>${esc(T("kills"))}</span></div><div class="stat"><b>${deaths.length}</b><span>${esc(T("deaths"))}</span></div>` +
    `<div class="stat"><b>${sb.score != null ? sb.score : "-"}</b><span>${esc(T("score"))}</span></div><div class="stat"><b>${(dist / 1000).toFixed(2)}</b><span>km</span></div></div>` +
    `<dl class="kv"><dt>${esc(T("kits"))}</dt><dd class="kits">${kitsUsed || "-"}</dd><dt>${esc(T("joined"))}</dt><dd>${p.join_tick < 0 ? "0:00" : fmtTime((p.join_tick - M.tMin) / TPS)}</dd>` +
    `<dt>${esc(T("left_"))}</dt><dd>${p.leave_tick != null ? fmtTime((p.leave_tick - M.tMin) / TPS) : "-"}</dd></dl>` +
    `<div id="liveInfo" class="live"></div><button id="followBtn" class="${S.follow ? "primary" : ""}">${esc(S.follow ? T("unfollow") : T("follow"))}</button>`;
  if (veh.size) html += `<h4>${esc(T("vehicles_used"))}</h4>` + [...veh].map(([n, c]) => `<div>${esc(n)} ×${c}</div>`).join("");
  const ev = [...mine.map((k) => ({ ...k, kind: "K" })), ...deaths.map((k) => ({ ...k, kind: "D" }))].sort((a, b) => a.tick - b.tick);
  html += `<h4>${esc(T("events"))} (${ev.length})</h4><div class="feedlist short">` + ev.map((k) => {
    const other = M.players.get(k.kind === "K" ? k.v : k.k);
    return `<div class="fl" data-t="${k.tick}"><span class="ts">${fmtTime((k.tick - M.tMin) / TPS)}</span><span class="k ${k.kind === "K" ? "good" : "bad"}">${esc(T(k.kind === "K" ? "k_kill" : "k_death"))}</span><span>${esc(other ? other.name : "?")} <span class="muted">[${esc(k.w || "?")}]</span></span></div>`;
  }).join("") + "</div>";
  box.innerHTML = html;
  $("followBtn").onclick = () => ui.cb.follow();
  updateLive(S.tick | 0);
  box.querySelectorAll(".fl[data-t]").forEach((r) => { r.onclick = () => ui.cb.seek(Math.max(M.tMin, +r.dataset.t - 3 * TPS)); });
}

// ------------------------------------------------------------------------------------------- live map overlays (4 Hz)
/** What the selected player holds / sits in right now (4 Hz, with the HUD). */
function updateLive(tick) {
  const box = $("liveInfo"), p = S.sel != null ? M.players.get(S.sel) : null;
  if (!box || !p) return;
  const seat = seatOf(p.player_id, tick), rows = [];
  if (seat) rows.push([T("in_vehicle"), esc(vehicleLabel(seat.track.tpl))]);
  else {
    const w = heldWeapon(p, tick);
    rows.push([T("weapon"), !w ? "-" : w.none ? esc(T("no_weapon")) : w.names ? w.names.map(esc).join(" / ") : "#" + w.idx]);
  }
  box.innerHTML = `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl><div class="note">${esc(T("no_hp_ammo"))}</div>`;
}

export function updateHud(tick, playing, speed) {
  updateLive(tick);
  drawHudBar(tick);
  updateKillFeed(tick, playing, speed);
  updateScoreboard();
  markLogNow(playing);
}
