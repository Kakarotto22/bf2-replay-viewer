// Export a scene as a .bf2demo: pick a start and an end on the timeline, download a recording the game can open.
import { T } from "./i18n.js";
import { M } from "./model.js";
import { S } from "./state.js";
import { $, TPS, el, esc, fmtTime } from "./util.js";

const clip = { start: null, end: null, lead: 8, id: null, sign: true };

export const setClipDemo = (id) => { clip.id = id; clip.start = clip.end = null; };

function url() {
  const q = new URLSearchParams();
  if (clip.start != null) { q.set("start", Math.round(clip.start)); q.set("lead", clip.lead); }
  if (clip.end != null) q.set("end", Math.round(clip.end));
  if (!clip.sign) q.set("signature", "0");
  return `/api/demos/${clip.id}/clip?${q}`;
}

export function buildClip() {
  const root = $("clipBody"); root.innerHTML = "";
  const time = (t) => (t == null ? "-" : fmtTime((t - M.tMin) / TPS));
  root.append(el("p", "note", esc(T("clip_help"))));
  const row = el("div", "cliprow");
  row.innerHTML = `<button id="clipSetStart">${esc(T("clip_set_start"))}</button><b id="clipStart">${time(clip.start)}</b>
    <button id="clipSetEnd">${esc(T("clip_set_end"))}</button><b id="clipEnd">${time(clip.end)}</b>`;
  root.append(row);
  const lead = el("label", "check", `<span>${esc(T("clip_lead"))}</span><input id="clipLead" type="number" min="0" max="60" step="1" value="${clip.lead}" style="width:64px">`);
  root.append(lead);
  const sign = el("label", "check", `<input id="clipSign" type="checkbox" ${clip.sign ? "checked" : ""}><span>${esc(T("clip_sign"))}</span>`);
  root.append(sign);
  const go = el("button", "primary", esc(T("clip_download")));
  root.append(go, el("p", "note", esc(T("clip_warning"))));
  const refresh = () => { $("clipStart").textContent = time(clip.start); $("clipEnd").textContent = time(clip.end); go.disabled = clip.start == null && clip.end == null; };
  $("clipSetStart").onclick = () => { clip.start = S.tick; if (clip.end != null && clip.end <= clip.start) clip.end = null; refresh(); };
  $("clipSetEnd").onclick = () => { clip.end = S.tick; if (clip.start != null && clip.end <= clip.start) clip.start = null; refresh(); };
  $("clipSign").onchange = (e) => { clip.sign = e.target.checked; };
  $("clipLead").onchange = (e) => { clip.lead = Math.min(60, Math.max(0, +e.target.value || 0)); };
  go.onclick = () => { window.location.href = url(); };
  refresh();
}
