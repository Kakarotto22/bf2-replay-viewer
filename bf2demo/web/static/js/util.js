// Small helpers shared by every module.
export const $ = (id) => document.getElementById(id);
export const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
export const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const TPS = 30;

export function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(s).padStart(2, "0");
}
export const fmtBytes = (n) => (n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : (n / 1e3).toFixed(0) + " KB");
export const prettyMap = (m) => (m || "").replace(/_/g, " ");

/** Last index i with key(i) <= value over a sorted array (or -1). `arr` may be typed. */
export function bsearch(arr, value) {
  let lo = 0, hi = arr.length - 1, r = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (arr[mid] <= value) { r = mid; lo = mid + 1; } else hi = mid - 1; }
  return r;
}

/** Value of a `[[tick, value], ...]` history at `tick` (binary search), or `dflt` before the first entry. */
export function histAt(hist, tick, dflt) {
  if (!hist || !hist.length) return dflt;
  let lo = 0, hi = hist.length - 1, r = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (hist[mid][0] <= tick) { r = mid; lo = mid + 1; } else hi = mid - 1; }
  return r < 0 ? dflt : hist[r][1];
}

export async function api(path, opts, onHeaders) {
  const r = await fetch(path, opts);
  if (onHeaders) onHeaders(r.headers);                          // available before the body has arrived
  if (!r.ok && r.status !== 202) throw new Error(path + " -> " + r.status);
  return { status: r.status, json: await r.json() };
}
