// "Moments": every kill of the round filtered by what the killer and the victim were in (on foot, tank, helicopter, jet ...),
// by player and by a name search, listed with its time and marked on the timeline. Example: a helicopter that shot down a jet.
import { A, ICON, iconUrl, vehicleIconKey } from "./assets.js";
import { T } from "./i18n.js";
import { M, seatOf } from "./model.js";
import { vehicleLabel } from "./text.js";
import { S, invalidate } from "./state.js";
import { $, TPS, bsearch, el, esc, fmtTime } from "./util.js";

const CLASSES = [
  ["foot", ICON.soldier], ["tank", "ingame/vehicles/icons/minimap/mini_tank"], ["apc", "ingame/vehicles/icons/minimap/mini_apc"],
  ["jeep", "ingame/vehicles/icons/minimap/mini_jeep"], ["heli", "ingame/vehicles/icons/minimap/mini_attack_heli"],
  ["jet", "ingame/vehicles/icons/minimap/mini_jet"], ["boat", "ingame/vehicles/icons/minimap/mini_rib"],
  ["aa", "ingame/vehicles/icons/minimap/mini_aavehicle"],
];
const BY_ICON = { mini_jet: "jet", mini_attack_heli: "heli", mini_transport_heli: "heli", mini_tank: "tank", mini_apc: "apc", mini_jeep: "jeep", mini_buggy: "jeep",
  mini_rib: "boat", mini_alcac: "boat", mini_aavehicle: "aa", mini_artillery: "aa", mini_airdefsmall: "aa", mini_armourdefsmall: "aa" };
const BY_NAME = [[/(ahe_|usthe|chthe|mec.*he|heli|z10|z8|mi17|uh60|ah1|havoc|cobra|vodnic|littlebird|ec635)/, "heli"], [/(air_|usair|chair|mig|f35|f15|f18|j10|su3|a10|fantan|harrier)/, "jet"],
  [/(tnk|tank|m1a2|t90|type98)/, "tank"], [/(apc|lav|btr|wz551|aav)/, "apc"], [/(jeep|jep_|jeep|hmmwv|faav|hummer|buggy)/, "jeep"], [/(boat|rib|ship)/, "boat"],
  [/(igla|stinger|aas|tunguska|linebacker|ats|ars|bipod|tow|hj8)/, "aa"]];

const f = { killer: new Set(), victim: new Set(), killerPlayer: "", victimPlayer: "", q: "" };
let rows = [], cb = null;

function classOf(track) {
  if (!track || track.parachute) return "foot";
  const info = A.vehicles[track.tpl], icon = info && info.icon ? info.icon.split("/").pop() : vehicleIconKey(track.tpl).split("/").pop();
  if (BY_ICON[icon]) return BY_ICON[icon];
  const name = track.tpl.toLowerCase();
  for (const [re, cls] of BY_NAME) if (re.test(name)) return cls;
  return "other";
}
function vehicleOf(pid, tick) {
  const seat = seatOf(pid, tick) || seatOf(pid, tick - TPS / 2);       // a death can close the seat in the same tick
  return seat ? seat.track : null;
}

/** Adds what each side was in to every kill (needs the vehicle table, so it runs after the assets are loaded). */
function classify() {
  for (const k of M.kills) {
    const kt = vehicleOf(k.k, k.tick), vt = vehicleOf(k.v, k.tick), a = M.players.get(k.k), b = M.players.get(k.v);
    k.kc = classOf(kt); k.vc = classOf(vt);
    k.kv = kt && !kt.parachute ? vehicleLabel(kt.tpl) : ""; k.vv = vt && !vt.parachute ? vehicleLabel(vt.tpl) : "";
    k.blob = [a ? a.name : "", b ? b.name : "", k.w || "", k.kv, k.vv].join(" ").toLowerCase();
  }
}

function icon(key) { return `<img class="cico" src="${iconUrl(key)}" alt="">`; }
const clsLabel = (c) => T("cls_" + c);

function classChips(parent, set) {
  for (const [cls, key] of CLASSES) {
    const b = el("button", "ibtn small" + (set.has(cls) ? " on" : ""), `<span class="lg"><img src="${iconUrl(key)}" alt=""></span><small>${esc(clsLabel(cls))}</small>`);
    b.title = clsLabel(cls);
    b.onclick = () => { if (set.has(cls)) set.delete(cls); else set.add(cls); b.classList.toggle("on", set.has(cls)); apply(); };
    parent.append(b);
  }
}
function playerSelect(parent, key) {
  const sel = el("select"), list = M.doc.players.slice().sort((a, b) => a.name.localeCompare(b.name));
  sel.innerHTML = `<option value="">${esc(T("m_anyone"))}</option>` + list.map((p) => `<option value="${p.player_id}">${esc(p.name)}</option>`).join("");
  sel.value = f[key]; sel.onchange = () => { f[key] = sel.value; apply(); };
  parent.append(sel);
}

export function initMoments(callbacks) { cb = callbacks; }

export function buildMoments() {
  classify();
  const root = $("moments"); root.innerHTML = "";
  f.killer.clear(); f.victim.clear(); f.killerPlayer = f.victimPlayer = f.q = "";
  const side = (title, set, playerKey) => {
    root.append(el("h4", null, esc(T(title))));
    const grid = el("div", "ibtns four"); root.append(grid); classChips(grid, set);
    playerSelect(root, playerKey);
  };
  side("m_killer", f.killer, "killerPlayer");
  side("m_victim", f.victim, "victimPlayer");
  const q = el("input"); q.type = "search"; q.placeholder = T("m_search"); q.oninput = () => { f.q = q.value.toLowerCase(); apply(); };
  root.append(el("h4", null, esc(T("m_text")))); root.append(q);
  const bar = el("div", "mbar", `<span id="mCount"></span><span class="spacer"></span><button id="mPrev" title="${esc(T("m_prev"))}">‹</button><button id="mNext" title="${esc(T("m_next"))}">›</button><button id="mClear">${esc(T("m_clear"))}</button>`);
  const list = el("div", "feedlist moments"); list.id = "mList";
  root.append(bar, list);
  $("mPrev").onclick = () => step(-1); $("mNext").onclick = () => step(1);
  $("mClear").onclick = () => { buildMoments(); };
  apply();
}

function apply() {
  const ok = (set, cls) => !set.size || set.has(cls);
  rows = M.kills.filter((k) => ok(f.killer, k.kc) && ok(f.victim, k.vc) &&
    (!f.killerPlayer || k.k === +f.killerPlayer) && (!f.victimPlayer || k.v === +f.victimPlayer) && (!f.q || k.blob.includes(f.q)));
  const active = f.killer.size || f.victim.size || f.killerPlayer || f.victimPlayer || f.q;
  S.moments = active ? rows.map((k) => k.tick) : [];
  $("mCount").textContent = `${rows.length} ${T("m_count")}`;
  const list = $("mList"); list.innerHTML = "";
  const frag = document.createDocumentFragment(), MAX = 600;
  for (const k of rows.slice(0, MAX)) {
    const a = M.players.get(k.k), b = M.players.get(k.v);
    const key = (c) => (CLASSES.find((x) => x[0] === c) || [0, ICON.soldier])[1];
    const row = el("div", "fl", `<span class="ts">${fmtTime((k.tick - M.tMin) / TPS)}</span><span class="mk">${icon(key(k.kc))}</span>` +
      `<span><b>${esc(a ? a.name : "?")}</b>${k.kv && k.kv !== k.w ? ` <span class="muted">${esc(k.kv)}</span>` : ""} <span class="muted">[${esc(k.w || "?")}]</span> ` +
      `${icon(key(k.vc))}<b>${esc(b ? b.name : "?")}</b>${k.vv ? ` <span class="muted">${esc(k.vv)}</span>` : ""}</span>`);
    row.onclick = () => { cb.seek(Math.max(M.tMin, k.tick - 4 * TPS)); cb.focus(k.k); };
    frag.append(row);
  }
  list.append(frag);
  if (rows.length > MAX) list.append(el("div", "muted", `+${rows.length - MAX}`));
  invalidate();
}

function step(dir) {
  if (!rows.length) return;
  const ticks = rows.map((k) => k.tick), now = S.tick + 4 * TPS;
  let i = dir > 0 ? ticks.findIndex((t) => t > now + 1) : bsearch(ticks, now - TPS * 5);
  if (i < 0) i = dir > 0 ? 0 : ticks.length - 1;
  cb.seek(Math.max(M.tMin, ticks[i] - 4 * TPS));
}
