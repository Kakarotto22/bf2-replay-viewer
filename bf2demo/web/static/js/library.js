// The recording library page: cards with search, map filter and sort.
import { T } from "./i18n.js";
import { $, api, el, esc, fmtBytes, fmtTime, prettyMap } from "./util.js";

let library = [];

export function parseNameInfo(name) {          // dalian_plant_20261012-1320_2h.bf2demo
  const m = name.match(/^(.*?)_(\d{8})-(\d{4})_(\d+)h/);
  return m ? { map: m[1], date: `${m[2].slice(0, 4)}-${m[2].slice(4, 6)}-${m[2].slice(6)} ${m[3].slice(0, 2)}:${m[3].slice(2)}`, humans: +m[4] } : null;
}

export async function loadLibrary() {
  library = (await api("/api/demos")).json;
  const maps = [...new Set(library.map((d) => (d.summary ? d.summary.map : (parseNameInfo(d.name) || {}).map)).filter(Boolean))].sort();
  const sel = $("libMap"), cur = sel.value;
  sel.innerHTML = `<option value="">${esc(T("all_maps"))}</option>` + maps.map((m) => `<option value="${esc(m)}">${esc(prettyMap(m))}</option>`).join("");
  sel.value = cur;
  renderLibrary();
}

export function renderLibrary() {
  const q = $("libSearch").value.trim().toLowerCase(), map = $("libMap").value, human = $("libHumans").checked, sort = $("libSort").value;
  const items = library.filter((d) => {
    const s = d.summary, hay = (d.name + " " + (s ? s.map + " " + s.server : "")).toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (map && (s ? s.map : (parseNameInfo(d.name) || {}).map) !== map) return false;
    if (human && s && !s.humans) return false;
    return true;
  });
  const key = { date: (d) => d.mtime, players: (d) => (d.summary ? d.summary.players : 0), kills: (d) => (d.summary ? d.summary.kills : 0), duration: (d) => (d.summary ? d.summary.duration_s : 0) }[sort];
  items.sort((a, b) => key(b) - key(a));
  $("libStats").textContent = `${items.length} / ${library.length} ${T("demos")}`;
  const box = $("cards"); box.innerHTML = "";
  if (!items.length) box.append(el("div", "muted", esc(T("empty"))));
  for (const d of items) {
    const s = d.summary, info = parseNameInfo(d.name), map = s ? s.map : info ? info.map : d.name.replace(/\.bf2demo$/i, "");
    const card = el("div", "card"), thumb = el("div", "thumb"), body = el("div", "body");
    thumb.style.backgroundImage = `url(/api/maps/${encodeURIComponent(map)}.png)`;
    body.innerHTML = `<h3>${esc(prettyMap(map))}</h3><div class="meta"><span>${esc(s ? s.recorded_at : info ? info.date : new Date(d.mtime * 1000).toLocaleString())}</span>` +
      (s ? `<span>${fmtTime(s.duration_s)}</span><span>${s.humans} ${esc(T("humans"))}${s.players > s.humans ? ` + ${s.players - s.humans} ${esc(T("bots"))}` : ""}</span><span>${s.kills} ${esc(T("kills"))}</span><span>${esc(s.server || "")}</span>`
         : `<span>${fmtBytes(d.size)}</span>${info ? `<span>${info.humans} ${esc(T("humans"))}</span>` : ""}`) +
      `<span class="badge ${d.status}">${esc(T(d.status))}</span></div>`;
    card.append(thumb, body);
    card.onclick = () => { location.hash = "#/demo/" + d.id; };
    box.append(card);
  }
}

export function initLibrary(onUpload) {
  for (const id of ["libSearch", "libMap", "libHumans", "libSort"]) $(id).oninput = renderLibrary;
  $("uploadInput").onchange = async (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    await onUpload(fd);
  };
}
