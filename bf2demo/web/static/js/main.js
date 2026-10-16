// Entry point: routing, loading a recording, playback clock, map interaction and the render loop.
import { A, HUD_TEXTURES, loadAssets, preload, vehicleInfo } from "./assets.js";
import { loadFonts } from "./font.js";
import { animating as hudAnimating, drawHudBar } from "./hudbar.js";
import { initScoreboard, isOpen, redrawScoreboard, setOpen } from "./scoreboard.js";
import { T, applyLang, lang, setLang } from "./i18n.js";
import { setClipDemo } from "./clipui.js";
import { initMoments } from "./moments.js";
import { setPerspective } from "./palette.js";
import { initLibrary, loadLibrary, renderLibrary } from "./library.js";
import { FRAME, PERF, V, drawMap, initMap, loadHd, pick, resizeMap, s2w, setBackdrop, smallDevice, zoomAt } from "./mapview.js";
import { M, buildModel, commanderOf, setRules, kitOf, occupants, playerPos, teamName, trackTeam } from "./model.js";
import { buildPanels, resetKillFeed, renderBoard, renderPlayerPanel, showTab, updateHud, initPanels } from "./panels.js";
import { S, invalidate, resetFilters, takeDirty } from "./state.js";
import { cpDisplayName, cpTokens, friendlyText, isNoise, vehicleLabel } from "./text.js";
import { dropTimelineCache, drawTimeline, initTimeline, resizeTimeline } from "./timeline.js";
import { $, TPS, api, clamp, esc, fmtTime, prettyMap } from "./util.js";

let raf = 0, lastHud = 0, lastAnim = 0, lastPulse = 0, hudPending = true, hoverTrack = null, routeToken = 0;
const pos = { x: 0, z: 0, h: -1, gap: false };

// ---------------------------------------------------------------------------------------------------- playback / clock
function seek(tick) { S.tick = clamp(Math.round(tick), M.tMin, M.tMax); setAnchor(); invalidate(); lastHud = 0; }
function stop() { S.playing = false; $("playBtn").innerHTML = "&#9654;"; }
function togglePlay() {
  if (!M) return;
  S.playing = !S.playing; $("playBtn").innerHTML = S.playing ? "&#10074;&#10074;" : "&#9654;";
  if (S.playing) { if (S.tick >= M.tMax) S.tick = M.tMin; setAnchor(); }
}
// Playback is anchored to the wall clock (tick = anchor tick + elapsed real seconds x 30 x speed x rate), so a slow frame, a busy machine or a
// background tab can never make the replay fall behind or run ahead; the anchor is renewed whenever the tick, the speed or the rate changes.
let anchor = { ms: 0, tick: 0 };
const setAnchor = () => { anchor = { ms: performance.now(), tick: S.tick }; };
function frame(ts) {
  raf = requestAnimationFrame(frame);
  if (!M || $("viewer").hidden) return;
  if (S.playing) {
    S.tick = anchor.tick + ((performance.now() - anchor.ms) / 1000) * TPS * S.speed * S.rate;
    if (S.tick >= M.tMax) { S.tick = M.tMax; stop(); }
    invalidate();
  }
  if (FRAME.animating && ts - lastAnim > 33) { invalidate(); lastAnim = ts; }       // a UAV sweep turns in real time (about 30 fps)
  if (hudAnimating && ts - lastPulse > 33) { drawHudBar(S.tick | 0); lastPulse = ts; }   // a bleeding ticket counter pulses smoothly (about 30 fps)
  if (takeDirty()) { FRAME.animating = false; drawMap(); drawTimeline(); hudPending = true; }
  const now = performance.now();
  if (hudPending && now - lastHud >= 250) {                    // text overlays change slowly: 4 Hz is plenty
    hudPending = false; lastHud = now; updateHud(S.tick | 0, S.playing, S.speed);
    $("clock").textContent = fmtTime((S.tick - M.tMin) / TPS) + " / " + fmtTime((M.tMax - M.tMin) / TPS);
    if (new URLSearchParams(location.search).has("perf")) $("perf").textContent = `draw ${PERF.ms.toFixed(2)} ms · ${PERF.frames} frames`;
  }
}

// ------------------------------------------------------------------------------------------------------------ routing
async function route() {
  const token = ++routeToken, m = location.hash.match(/^#\/demo\/([0-9a-f]+)(?:\?(.*))?/);
  stop();
  if (!m) { $("viewer").hidden = true; $("library").hidden = false; $("crumb").textContent = ""; await loadLibrary(); return; }
  $("library").hidden = true; $("viewer").hidden = false; showLoading(T("loading"));
  try {
    let r;
    for (;;) {
      r = await api("/api/demos/" + m[1]);
      if (r.status !== 202) break;
      if (r.json.status === "error") throw new Error(r.json.error || "parse error");
      $("loadingText").textContent = T("parsing_long");
      await new Promise((ok) => setTimeout(ok, 1500));
      if (token !== routeToken) return;
    }
    await openDemo(r.json, new URLSearchParams(m[2] || ""), m[1]);
    hideLoading();
  } catch (e) { hideLoading(); alert(e.message); location.hash = "#/"; }
}
const showLoading = (text) => { $("loading").hidden = false; $("loadingText").textContent = text; };
const hideLoading = () => { $("loading").hidden = true; };

async function openDemo(doc, q, id) {
  buildModel(doc); setClipDemo(id); resetFilters();
  S.persp = M.viewTeam; setPerspective(S.persp); S.iconScale = 1; S.speed = 1;
  S.tick = M.tMin; S.sel = null; S.follow = false; S.view = { cx: 0, cz: 0, zoom: 1 };
  await loadAssets();
  await loadFonts(["ingameChatFontLocalOutline_8", "digitalNumbers", "hudFontLocalBold_9", "hudFontBold_9", "scoreboardFontLocal_8"]);
  if (A.installed) await preload([...HUD_TEXTURES, ...Object.values(A.kits)]);
  for (const tr of M.tracks) tr.info = vehicleInfo(tr.tpl);
  for (const cp of doc.control_points) cp.label = cpDisplayName(cp.template);
  M.feed = M.feed.filter((f) => !isNoise(f));
  for (const f of M.feed) f.display = friendlyText(f.text);
  let size = 0, image = null;
  try {
    const info = (await api("/api/maps/" + doc.demo.map)).json;
    if (info.available && info.world_size) {
      size = info.world_size; M.uncapturable = new Set(info.uncapturable || []); setRules(info.rules); image = new Image(); image.src = "/api/maps/" + doc.demo.map + ".png";
      await new Promise((ok) => { image.onload = image.onerror = ok; });
      if (!image.naturalWidth) image = null;
    }
  } catch (e) { image = null; }
  if (!image) {                                                // no game install or a custom map: a grid fitted to the recorded positions
    let far = 100;
    for (const t of M.tracks) for (let i = 0; i < t.x.length; i++) far = Math.max(far, Math.abs(t.x[i]), Math.abs(t.z[i]));
    for (const c of doc.control_points) far = Math.max(far, Math.abs(c.position[0]), Math.abs(c.position[2]));
    size = Math.ceil((far * 2.1) / 100) * 100;
  }
  setBackdrop(image, size);
  if (smallDevice()) S.layers.hd = false;                      // a phone loads the detailed map only when it is switched on (More options)
  if (image && S.layers.hd) loadHd(doc.demo.map);
  $("crumb").innerHTML = `<a href="#/">${esc(T("back"))}</a> / ${esc(prettyMap(doc.demo.map))} <span class="muted">${esc(doc.demo.recorded_at || "")}</span>`;
  setOpen(false); buildPanels(); buildSpeed(); resize();
  if (q.has("t")) seek(M.tMin + +q.get("t") * TPS);
  if (q.has("p")) select(+q.get("p"), true);
  if (q.has("z")) S.view.zoom = +q.get("z");
  if (q.has("board")) setOpen(true);
  if (q.has("play")) { S.speed = SPEEDS.reduce((a, b) => (Math.abs(b - +q.get("play")) < Math.abs(a - +q.get("play")) ? b : a));  $("speed").value = String(S.speed); togglePlay(); }
  if (q.has("perf") || new URLSearchParams(location.search).has("perf")) $("perf").hidden = false;
  invalidate();
}

function resize() {
  if (!M) return;
  const r = $("mapWrap").getBoundingClientRect();
  resizeMap(r.width, r.height); resizeTimeline(); dropTimelineCache(); invalidate(); redrawScoreboard(); resetKillFeed();
}
// Playback speeds as the game's demo viewer names them (percent of real time), plus faster ones for long rounds.
export const SPEEDS = [0.05, 0.25, 0.5, 1, 1.5, 3, 6, 10, 20, 30, 60];
function buildSpeed() {
  const s = $("speed"); s.innerHTML = SPEEDS.map((v) => `<option value="${v}">${Math.round(v * 100)}%</option>`).join("");
  s.value = String(SPEEDS.includes(S.speed) ? S.speed : 1); s.onchange = () => { S.speed = +s.value; setAnchor(); };
}

// --------------------------------------------------------------------------------------------------------- selection
function select(pid, jump) {
  S.sel = !jump && S.sel === pid ? null : pid;
  if (S.sel != null) {
    showTab("player");
    if (jump && playerPos(S.sel, S.tick | 0, pos)) { S.view.cx = pos.x; S.view.cz = pos.z; }
  } else S.follow = false;
  renderBoard(); renderPlayerPanel(); invalidate();
}
const callbacks = { seek, select, focus, rate: setAnchor, follow: () => { S.follow = !S.follow; renderPlayerPanel(); invalidate(); } };

/** Select a player and centre the map on them without leaving the current tab (used by the moments list). */
function focus(pid) {
  S.sel = pid;
  if (playerPos(pid, S.tick | 0, pos)) { S.view.cx = pos.x; S.view.cz = pos.z; }
  renderBoard(); renderPlayerPanel(); invalidate();
}

// -------------------------------------------------------------------------------------------------- map interaction
function initMapInput() {
  const cv = $("map"), tip = $("tip");
  const ptrs = new Map();                          // active pointers (a finger each): one pans, two pinch-zoom
  let drag = null, moved = false, pinch = null;
  const local = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top, r]; };
  const showTip = (tr, mx, my, r) => {
    if (tr) { tip.innerHTML = tipHtml(tr); tip.hidden = false; tip.style.left = Math.max(0, Math.min(mx + 14, r.width - 220)) + "px"; tip.style.top = my + 14 + "px"; } else tip.hidden = true;
  };
  const pinchNow = () => { const [a, b] = [...ptrs.values()]; return { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; };
  cv.onpointerdown = (e) => {
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY }); cv.setPointerCapture(e.pointerId); cv.classList.add("drag");
    if (ptrs.size === 2) { drag = null; moved = true; pinch = pinchNow(); return; }
    drag = { x: e.clientX, y: e.clientY, cx: S.view.cx, cz: S.view.cz }; moved = false;
  };
  cv.onpointermove = (e) => {
    const [mx, my, r] = local(e);
    if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && ptrs.size === 2) {                // two fingers: zoom about their midpoint and follow it
      const now = pinchNow(), k = Math.min(V.W, V.H) / V.worldSize * S.view.zoom;
      S.follow = false; S.view.cx -= (now.x - pinch.x) / k; S.view.cz += (now.y - pinch.y) / k;
      zoomAt(now.x - r.left, now.y - r.top, now.d / pinch.d); pinch = now; return;
    }
    if (drag) {
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > (e.pointerType === "mouse" ? 3 : 8)) moved = true;
      if (moved) {
        const k = Math.min(V.W, V.H) / V.worldSize * S.view.zoom; S.follow = false;
        S.view.cx = drag.cx - (e.clientX - drag.x) / k; S.view.cz = drag.cz + (e.clientY - drag.y) / k; invalidate();
      }
      return;
    }
    if (e.pointerType !== "mouse") return;         // no hover on a touch screen: a tap shows the tip instead
    const tr = pick(mx, my);
    if (tr !== hoverTrack) { hoverTrack = tr; S.hover = tr; invalidate(); }
    showTip(tr, mx, my, r);
  };
  const release = (e, cancelled) => {
    ptrs.delete(e.pointerId);
    if (ptrs.size === 1) { const [p] = ptrs.values(); drag = { x: p.x, y: p.y, cx: S.view.cx, cz: S.view.cz }; pinch = null; moved = true; return; }   // one finger left after a pinch: keep panning, never a tap
    if (ptrs.size > 1) return;
    cv.classList.remove("drag"); drag = null; pinch = null;
    if (moved || cancelled) return;
    if (e.pointerType !== "mouse") { const [mx, my, r] = local(e); hoverTrack = pick(mx, my); S.hover = hoverTrack; showTip(hoverTrack, mx, my, r); }
    const tr = hoverTrack;
    if (tr && tr.kind === "soldier" && tr.owner != null) select(tr.owner, false);
    else if (tr && tr.cls === "UAVVehicle") { const c = commanderOf(tr.team, S.tick | 0); if (c) select(c.player_id, false); }
    else if (tr && tr.kind === "vehicle") { const crew = occupants(tr, S.tick | 0); if (crew.length) select(crew[0], false); }
    else if (S.sel != null) select(S.sel, false);
  };
  cv.onpointerup = (e) => release(e, false);
  cv.onpointercancel = (e) => release(e, true);
  cv.onwheel = (e) => { e.preventDefault(); const r = cv.getBoundingClientRect(); zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.18 : 1 / 1.18); };
  $("zIn").onclick = () => zoomAt(V.W / 2, V.H / 2, 1.4);
  $("zOut").onclick = () => zoomAt(V.W / 2, V.H / 2, 1 / 1.4);
  $("zFit").onclick = () => { S.view = { cx: 0, cz: 0, zoom: 1 }; S.follow = false; invalidate(); };
}
function tipHtml(tr) {
  const tick = S.tick | 0;
  if (tr.kind === "soldier") {
    const p = M.players.get(tr.owner), kit = p ? kitOf(p, tick) : null;
    return `<b>${esc(p ? p.name : tr.tpl)}</b><br><span class="muted">${esc(teamName(trackTeam(tr, tick)))}${kit != null ? " · " + esc(M.kitNames[kit] || "") : ""}</span>`;
  }
  if (tr.cls === "UAVVehicle") {                                   // who launched it: the commander of its side
    const c = commanderOf(tr.team, tick);
    return `<b>UAV</b><br><span class="muted">${esc(teamName(tr.team))}${c ? " · " + esc(c.name) : ""}</span>`;
  }
  const crew = occupants(tr, tick), name = vehicleLabel(tr.tpl);
  return `<b>${esc(name)}</b>` + (crew.length ? "<br>" + crew.map((id) => esc((M.players.get(id) || {}).name || "?")).join(", ") : "");
}

// ------------------------------------------------------------------------------------------------------------ keys
function initKeys() {
  window.addEventListener("keydown", (e) => {
    if (!M || $("viewer").hidden || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    const sp = $("speed");
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (e.code === "ArrowRight") seek(S.tick + (e.shiftKey ? 60 : 10) * TPS);
    else if (e.code === "ArrowLeft") seek(S.tick - (e.shiftKey ? 60 : 10) * TPS);
    else if (e.key === "+" || e.key === "=") { sp.selectedIndex = Math.min(sp.options.length - 1, sp.selectedIndex + 1); sp.onchange(); }
    else if (e.key === "-") { sp.selectedIndex = Math.max(0, sp.selectedIndex - 1); sp.onchange(); }
    else if (e.key === "f" || e.key === "F") callbacks.follow();
    else if (e.key === "Tab") { e.preventDefault(); setOpen(!isOpen()); }
    else if (e.key === "Escape" && isOpen()) setOpen(false);
    else if (e.key === "Escape") { S.sel = null; S.follow = false; renderBoard(); renderPlayerPanel(); invalidate(); }
  });
}

// ------------------------------------------------------------------------------------------------------------ boot
$("langBtn").onclick = () => {
  setLang(lang === "ar" ? "en" : "ar");
  if (M && !$("viewer").hidden) { buildPanels(); buildSpeed(); invalidate(); } else renderLibrary();
};
// the upload button starts hidden (no flash on a server without uploads) and is shown when the server accepts uploads
api("/api/game").then((r) => {
  if (r.json.upload !== false) document.querySelector('label[for="uploadInput"]').style.display = "";
  if (r.json.donate) showDonate(r.json.donate);
}).catch(() => {});

/** The support section (top bar button, library card, dialog) exists only when the server has a Telegram username or payment methods. */
function showDonate(d) {
  const methods = d.methods || [], tg = d.telegram ? "https://t.me/" + encodeURIComponent(d.telegram) : "";
  const dlg = $("donateDlg"), close = () => { dlg.hidden = true; }, open = (e) => { if (e) e.preventDefault(); dlg.hidden = false; };
  const top = $("donateBtn");                                  // the button opens the dialog: Telegram first, then every payment method, each with a QR code
  top.removeAttribute("href"); top.onclick = open; top.tabIndex = 0; top.hidden = false; $("donateCard").hidden = false;
  if (tg) { $("donateLink").href = tg; $("donateHandle").textContent = "@" + d.telegram; $("donateLink").hidden = false; $("donateCopy").hidden = false; }
  $("donateMore").hidden = false; $("donateMore").onclick = open;
  $("donateCopy").onclick = (e) => copyText("@" + d.telegram, e.currentTarget, "donate_copy");
  $("donateClose").onclick = close; dlg.onclick = (e) => { if (e.target === dlg) close(); };
  window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !dlg.hidden) close(); });
  const list = $("donateList"); list.textContent = "";
  const all = (tg ? [{ kind: "link", label: "Telegram", url: tg, text: "@" + d.telegram }] : []).concat(methods);
  for (const m of all) {                                       // text nodes only: nothing from the config is ever parsed as HTML
    const row = document.createElement("div"); row.className = "dm";
    const head = document.createElement("div"); head.className = "dm-head";
    const name = document.createElement("b"); name.textContent = m.label; head.append(name);
    if (m.network) { const net = document.createElement("span"); net.className = "dm-net"; net.textContent = m.network; head.append(net); }
    row.append(head);
    const payload = m.kind === "crypto" ? m.address : m.kind === "link" ? m.url : "";
    if (m.kind === "crypto") {
      const line = document.createElement("div"); line.className = "dm-addr";
      const code = document.createElement("code"); code.textContent = m.address;
      const btn = document.createElement("button"); btn.textContent = T("donate_copy_addr"); btn.onclick = () => copyText(m.address, btn, "donate_copy_addr");
      line.append(code, btn); row.append(line);
    }
    const actions = document.createElement("div"); actions.className = "dm-actions";
    if (m.kind === "link") {
      const a = document.createElement("a"); a.className = "btn primary"; a.href = m.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = m.text || (T("donate_open") + " " + new URL(m.url).hostname); actions.append(a);
    }
    if (payload && m.qr !== false) {                           // a QR code on demand (drawn in the browser by the bundled qrcode-generator, MIT)
      const qrBtn = document.createElement("button"); qrBtn.textContent = T("donate_qr"); let img = null;
      qrBtn.onclick = () => {
        if (img) { img.remove(); img = null; qrBtn.textContent = T("donate_qr"); return; }
        const qr = window.qrcode(0, "M"); qr.addData(payload); qr.make();
        img = document.createElement("img"); img.className = "dm-qr"; img.alt = m.label + " QR"; img.title = T("donate_scan"); img.src = qr.createDataURL(6, 0);
        row.append(img); qrBtn.textContent = T("donate_hide_qr");
      };
      actions.append(qrBtn);
    }
    if (actions.childNodes.length) row.append(actions);
    if (m.kind === "crypto" && payload && m.qr !== false) actions.querySelector("button").click();   // a wallet shows its QR code at once: copy the address or scan it
    if (m.note) { const note = document.createElement("div"); note.className = "dm-note"; note.textContent = m.note; row.append(note); }
    list.append(row);
  }
}
async function copyText(text, button, key) {
  try { await navigator.clipboard.writeText(text); } catch (e) { return; }
  button.textContent = T("donate_copied"); setTimeout(() => { button.textContent = T(key); }, 1500);
}
initLibrary(async (fd) => {
  showLoading(T("loading"));
  try { const r = await api("/api/upload", { method: "POST", body: fd }); hideLoading(); location.hash = "#/demo/" + r.json.id; }
  catch (e) { hideLoading(); alert(e.message); }
});
initMap($("map")); initMapInput(); initKeys(); initPanels(callbacks); initMoments(callbacks); initScoreboard(callbacks);
initTimeline((t) => seek(t));
$("playBtn").onclick = togglePlay;
A.onLoad = invalidate;
window.addEventListener("resize", resize);
if (window.ResizeObserver) { const ro = new ResizeObserver(() => resize()); ro.observe($("mapWrap")); ro.observe($("timeline")); }   // orientation change, wrapped transport bar, side panel moving below the map
window.addEventListener("hashchange", route);
applyLang(); route(); raf = requestAnimationFrame(frame);
window.bf2 = { S, get M() { return M; } };      // handle for debugging in the browser console
