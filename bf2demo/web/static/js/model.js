// The loaded recording: decoded tracks, seat intervals, per-player histories and the lookups the renderer needs.
import { TPS, bsearch, histAt } from "./util.js";

export const GAP_TICKS = 60;            // same constant as viewer_format.py: a silence this long between samples is a gap
const BUCKET = 30 * TPS;                // active-track index: one list per 30 s of the round
const CORPSE_TICKS = 4 * TPS;

export let M = null;

const KIND = { Soldier: "soldier", PlayerControlObject: "vehicle" };

function decodeTrack(r, tMax) {
  const n = r.dt.length, t = new Int32Array(n), x = new Float32Array(n), y = new Float32Array(n), z = new Float32Array(n), h = new Int16Array(r.h);
  let ct = r.t0, cx = 0, cy = 0, cz = 0;
  for (let i = 0; i < n; i++) { ct += r.dt[i]; cx += r.x[i]; cy += r.y[i]; cz += r.z[i]; t[i] = ct; x[i] = cx / 10; y[i] = cy / 10; z[i] = cz / 10; }
  const kind = KIND[r.cls] || "other", last = t[n - 1];
  let wt = null, wv = null;                                      // weapon in hand: ticks and item indexes (soldiers)
  if (r.wi) { const m = r.wi.length / 2; wt = new Int32Array(m); wv = new Int8Array(m); let c = r.t0; for (let i = 0; i < m; i++) { c += r.wi[2 * i]; wt[i] = c; wv[i] = r.wi[2 * i + 1]; } }
  let tEnd;
  if (kind === "soldier") tEnd = r.dead != null ? r.dead : r.end != null ? r.end : last;
  else if (kind === "vehicle") tEnd = r.wreck != null ? r.wreck : r.end != null ? r.end : tMax;   // parked vehicles get no updates: live until they explode (the burning wreck is not shown)
  else tEnd = r.end != null ? r.end : last;
  return { id: r.id, cls: r.cls, tpl: r.tpl, owner: r.owner, team: r.team || 0, t0: r.t0, t, x, y, z, h, kind, dead: r.dead, last,
           tEnd: Math.max(tEnd, r.t0), wt, wv, seats: [], info: null, parachute: r.tpl.toLowerCase().includes("parachute") };
}

export function buildModel(doc) {
  const tMin = doc.demo.first_tick, tMax = doc.demo.last_tick;
  const players = new Map(doc.players.map((p) => [p.player_id, p]));
  for (const p of doc.players) p.stats = { k: 0, d: 0, tk: 0 };
  const tracks = doc.tracks.map((r) => decodeTrack(r, tMax));

  for (const tr of tracks) if (tr.cls === "UAVVehicle") {            // a UAV circles: the map shows its scan circle with the icon fixed at the centre
    let sx = 0, sz = 0; for (let i = 0; i < tr.t.length; i++) { sx += tr.x[i]; sz += tr.z[i]; }
    tr.cx = sx / tr.t.length; tr.cz = sz / tr.t.length;
  }
  const byObject = new Map(), byOwner = new Map();
  for (const tr of tracks) {
    if (!byObject.has(tr.id)) byObject.set(tr.id, []);
    byObject.get(tr.id).push(tr);
    if (tr.owner != null && tr.kind === "soldier") { if (!byOwner.has(tr.owner)) byOwner.set(tr.owner, []); byOwner.get(tr.owner).push(tr); }
  }

  // seat intervals -> the vehicle track that was alive at the time (object ids are reused over a round)
  const seatsOf = new Map();
  for (const s of doc.seats || []) {
    const cands = byObject.get(s.o); if (!cands) continue;
    let tr = null; for (const c of cands) if (c.t0 <= s.a + 300 && (!tr || c.t0 >= tr.t0)) tr = c;
    if (!tr) continue;
    const seat = { p: s.p, a: s.a, b: s.b == null ? Infinity : s.b, track: tr };
    tr.seats.push(seat);
    if (!seatsOf.has(s.p)) seatsOf.set(s.p, []);
    seatsOf.get(s.p).push(seat);
  }
  for (const list of seatsOf.values()) list.sort((a, b) => a.a - b.a);
  for (const tr of tracks) tr.seats.sort((a, b) => a.a - b.a);
  for (const tr of tracks) tr.dropped = tr.parachute && tr.seats.length === 0;        // a parachute nobody sits in carries a vehicle drop
  for (const list of seatsOf.values()) list.starts = list.map((s) => s.a);

  const feed = doc.feed.slice().sort((a, b) => a.tick - b.tick);
  // a UAV object carries no team: it comes from the "UAV launched" events (UAVVehicleCreated names object and side)
  for (const tr of tracks) if (tr.cls === "UAVVehicle" && !tr.team) {
    let best = null;
    for (const f of feed) if (f.kind === "uav" && f.data && f.data.event === "UAVVehicleCreated" && f.data.object_id === tr.id && f.tick <= tr.t0 + 90) best = f;
    if (best) tr.team = best.data.team;
  }
  const kills = feed.filter((f) => f.kind === "kill" || f.kind === "teamkill").map((f) => ({
    tick: f.tick, k: f.data.killer_id, v: f.data.victim_id, w: f.data.weapon, tk: !!f.data.teamkill || f.kind === "teamkill", f,
    kx: 0, kz: 0, vx: 0, vz: 0, hasK: false, hasV: false }));

  // every line of the game's kill message: kills, team kills and suicides ("X is no more.")
  const logKills = feed.filter((f) => (f.kind === "kill" || f.kind === "teamkill" || f.kind === "suicide") && f.data && f.data.victim_id != null).map((f) => ({
    tick: f.tick, k: f.data.killer_id, v: f.data.victim_id, w: f.data.weapon, tk: f.kind === "teamkill" || !!f.data.teamkill, f,
    noWeapon: f.kind !== "suicide" && !f.data.weapon_template_id && f.data.weapon === "Killed" }));

  // commanders from the "X is the Y commander" / "became commander" log lines
  const commanders = new Map();
  for (const f of feed) {
    if (f.kind !== "commander" || !f.data || f.data.player_id == null || f.data.team == null) continue;
    if (!commanders.has(f.data.team)) commanders.set(f.data.team, []);
    commanders.get(f.data.team).push([f.tick, f.data.player_id]);
  }

  // active-track index
  // squad leaders from the "new squadleader" log lines; a squad with no such line keeps the leader flag of the last Player ghost state
  const leaders = new Map();
  for (const f of feed) {
    if (f.kind !== "squad" || !f.data || f.data.player_id == null || f.data.squad_id == null) continue;
    const p = players.get(f.data.player_id); if (!p) continue;
    const team = histAt(p.team_history, f.tick, p.team), key = team + ":" + f.data.squad_id;
    if (!leaders.has(key)) leaders.set(key, []);
    leaders.get(key).push([f.tick, f.data.player_id]);
  }

  // active-track index
  const nb = Math.floor((tMax - tMin) / BUCKET) + 2, buckets = Array.from({ length: nb }, () => []);
  const bi = (tick) => Math.max(0, Math.min(nb - 1, Math.floor((tick - tMin) / BUCKET)));
  for (const tr of tracks) { const to = tr.kind === "soldier" ? tr.tEnd + CORPSE_TICKS : tr.tEnd; for (let b = bi(tr.t0); b <= bi(to); b++) buckets[b].push(tr); }

  const ticketTicks = {}; for (const t in doc.tickets) ticketTicks[t] = doc.tickets[t].map((x) => x[0]);
  M = { rules: null, logKills, logTicks: logKills.map((k) => k.tick), logOf: new Map(logKills.map((k) => [k.f, k])), bleeds: {}, uncapturable: new Set(), leaders, commanders, doc, tMin, tMax, players, tracks, byObject, byOwner, seatsOf, feed, kills, buckets, bucketOf: bi,
        viewTeam: ((doc.players.find((p) => !p.is_ai) || doc.players[0] || {}).team) || 1, killTicks: kills.map((k) => k.tick), ticketTicks, teamNames: doc.team_names || {}, kitNames: doc.kit_names, tmp: { x: 0, z: 0, h: -1, gap: false }, tmp2: { x: 0, z: 0, h: -1, gap: false } };
  computeBleeds(feed);
  for (const k of kills) {
    const a = players.get(k.k), b = players.get(k.v);
    if (a && k.k !== k.v) (k.tk ? a.stats.tk++ : a.stats.k++);
    if (b) b.stats.d++;
    const o = M.tmp2;
    if (playerPos(k.k, k.tick, o)) { k.kx = o.x; k.kz = o.z; k.hasK = true; }
    if (playerPos(k.v, k.tick, o)) { k.vx = o.x; k.vz = o.z; k.hasV = true; }
  }
  return M;
}

export const activeTracks = (tick) => M.buckets[M.bucketOf(tick)];
export const isLive = (tr, tick) => tick >= tr.t0 && tick <= tr.tEnd;
export const isCorpse = (tr, tick) => tr.kind === "soldier" && tr.dead != null && tick > tr.dead && tick <= tr.dead + CORPSE_TICKS;

/** Position of a track at `tick` written into `out` ({x, z, h, gap}). Inside a gap the last known position is held. */
export function samplePos(tr, tick, out) {
  const n = tr.t.length;
  const i = bsearch(tr.t, tick);
  out.gap = false;
  if (i < 0) { out.x = tr.x[0]; out.z = tr.z[0]; out.h = tr.h[0]; return out; }
  if (i >= n - 1) { out.x = tr.x[n - 1]; out.z = tr.z[n - 1]; out.h = tr.h[n - 1]; out.gap = tick - tr.t[n - 1] > GAP_TICKS && tr.kind !== "vehicle"; return out; }
  const span = tr.t[i + 1] - tr.t[i];
  if (span > GAP_TICKS) {                      // no updates for a while: hold, then jump at the next sample
    out.x = tr.x[i]; out.z = tr.z[i]; out.h = tr.h[i]; out.gap = tr.kind === "soldier" && tick - tr.t[i] > GAP_TICKS; return out;
  }
  const f = (tick - tr.t[i]) / span;
  let h = tr.h[i];
  if (h >= 0 && tr.h[i + 1] >= 0) { let d = tr.h[i + 1] - h; if (d > 180) d -= 360; if (d < -180) d += 360; h = (h + d * f + 360) % 360; }
  out.x = tr.x[i] + (tr.x[i + 1] - tr.x[i]) * f; out.z = tr.z[i] + (tr.z[i + 1] - tr.z[i]) * f; out.h = h;
  return out;
}

export function seatOf(pid, tick) {
  const list = M.seatsOf.get(pid); if (!list) return null;
  const i = bsearch(list.starts, tick);
  return i >= 0 && tick < list[i].b ? list[i] : null;
}

/** Where a player is at `tick`: inside a vehicle (its position) or on foot (soldier track). False when unknown. */
export function playerPos(pid, tick, out) {
  const seat = seatOf(pid, tick);
  if (seat) { samplePos(seat.track, Math.min(tick, seat.track.last), out); return true; }
  const trs = M.byOwner.get(pid); if (!trs) return false;
  let best = null;
  for (const tr of trs) if (tick >= tr.t0 && tick <= tr.tEnd + CORPSE_TICKS) best = tr;
  if (!best) return false;
  samplePos(best, Math.min(Math.max(tick, best.t0), best.last), out);
  return true;
}

export const teamOfPlayer = (p, tick) => { const t = histAt(p.team_history, tick, p.team); return t == null ? 0 : t; };
export const kitOf = (p, tick) => histAt(p.kit_history, tick, null);
export const squadOf = (p, tick) => histAt(p.squad_history, tick, 0);
export const rankOf = (p, tick) => histAt(p.rank_history, tick, null);

export function occupants(tr, tick) {
  const out = [];
  for (const s of tr.seats) if (s.a <= tick && tick < s.b) out.push(s.p);
  return out;
}
export function trackTeam(tr, tick) {
  if (tr.kind === "soldier") { const p = M.players.get(tr.owner); return p ? teamOfPlayer(p, tick) : tr.team; }
  for (const s of tr.seats) if (s.a <= tick && tick < s.b) { const p = M.players.get(s.p); if (p) return teamOfPlayer(p, tick); }
  return tr.team;
}
export const teamName = (t) => (M.teamNames && M.teamNames[t]) || (t === 0 ? "-" : "Team " + t);

/** Is the player the leader of their squad at `tick`? */
export function isLeader(p, tick) {
  const sq = squadOf(p, tick);
  if (sq <= 0) return false;
  const hist = M.leaders.get(teamOfPlayer(p, tick) + ":" + sq);
  if (!hist) return !!(p.leader && !p.leave_tick);
  let current = null;
  for (const [t, pid] of hist) { if (t > tick) break; current = pid; }
  return current === p.player_id;
}

/** Is the player the commander of their side at `tick`? */
export function isCommander(p, tick) {
  const hist = M.commanders.get(teamOfPlayer(p, tick));
  if (!hist) return false;
  let current = null;
  for (const [t, pid] of hist) { if (t > tick) break; current = pid; }
  return current === p.player_id;
}

/** The commander player of a side at `tick` (the one who launches its UAVs), or null. */
export function commanderOf(team, tick) {
  const hist = M.commanders.get(team);
  if (!hist) return null;
  let current = null;
  for (const [t, pid] of hist) { if (t > tick) break; current = pid; }
  return current == null ? null : M.players.get(current) || null;
}

// ----------------------------------------------------------------------------------------------- tickets, time, scoreboard
/** Ticks at which a team lost a ticket with none of its players dying within 3 ticks: the flag bleed (the server's `ticketChangePerSecond`
 *  applied by `updateTicketLoss`, replicated like every other ticket change). On dragon_valley (9 flags against 1) these are one ticket
 *  every 187.5 ticks (9.6 a minute) while a death costs its team one ticket at the very tick of the kill. */
function computeBleeds(feed) {
  const deaths = { 1: [], 2: [] };
  for (const f of feed) {
    if (!["kill", "teamkill", "suicide", "death"].includes(f.kind) || !f.data || f.data.victim_id == null) continue;
    const p = M.players.get(f.data.victim_id); if (!p) continue;
    const team = teamOfPlayer(p, f.tick); if (deaths[team]) deaths[team].push(f.tick);
  }
  for (const team of [1, 2]) {
    deaths[team].sort((a, b) => a - b);
    const hist = M.doc.tickets[team] || [], out = [];
    for (let i = 1; i < hist.length; i++) {
      if (hist[i][1] >= hist[i - 1][1]) continue;
      const t = hist[i][0], j = bsearch(deaths[team], t + 3);
      if (!(j >= 0 && deaths[team][j] >= t - 3)) out.push(t);
    }
    M.bleeds[team] = out;
  }
}

/**
 * Tickets of `team` at `tick`, or null while unknown. The first record of the ScoreManager (its full state at the start of the recording)
 * holds 0 for both teams in every sample, and the real count only arrives with the first change (599 after a start of 600, 659 after 660, ...):
 * that first 0 is the object's default, not a count, so it is not shown.
 */
export function ticketsAt(team, tick) {
  const h = (M.doc.tickets[team] || []), i = bsearch(M.ticketTicks[team] || [], tick);
  return i < 0 || (i === 0 && h[0][1] === 0) ? null : h[i][1];
}

/** The level's bleed parameters for this recording's mode and size (`maps.ticket_rules`), or none (custom map / no game install). */
export function setRules(rules) {
  const d = M.doc.demo, areas = rules && rules.areas && rules.areas[d.mode + "/" + d.map_size];
  M.rules = areas && Object.keys(areas).length ? { loss: rules.loss, areas } : null;
}

/** Area held by each side: the sum of `areaValueTeamN` of the control points owned by team N. */
function areaHeld(tick) {
  const A = { 1: 0, 2: 0 };
  for (const cp of M.doc.control_points) {
    const t = histAt(cp.history, tick, cp.initial_team), a = M.rules.areas[(cp.template || "").toLowerCase()];
    if ((t === 1 || t === 2) && a) A[t] += a[t - 1];
  }
  return A;
}

/**
 * Tickets per minute a team loses to the flags at `tick` (0 when it is not bleeding). The server's rule (`updateTicketLoss` of gpm_cq.py): the team
 * loses `lossPerMin * (area of the other side - own area) / 100` a minute while the other side holds an area of at least 100 and more than it does.
 * Checked on three recordings: dragon_valley 9 flags of 12 against 1 gives 10 * (108 - 12) / 100 = 9.6 a minute = the one ticket per 187.5 ticks in the
 * recording, and zatar_wetlands loses exactly 25 tickets per 5 minutes with 4 of 6 flags held by the other side. Without the level's parameters
 * (custom maps) the rate is estimated from the spacing of the decrements that no death explains, and only for the side with fewer flags.
 */
export function bleedRate(team, tick) {
  if (M.rules) {
    const A = areaHeld(tick), over = A[3 - team] - A[team];
    return A[3 - team] >= 100 && over > 0 ? ((M.rules.loss[team] || 0) * over) / 100 : 0;
  }
  const b = M.bleeds[team] || [], i = bsearch(b, tick);
  if (i < 1) return 0;
  const flags = flagCounts(tick);
  if (flags[team] >= flags[3 - team]) return 0;
  const gap = b[i] - b[i - 1];
  if (gap > 40 * TPS || tick - b[i] > Math.max(gap * 1.6, 4 * TPS)) return 0;
  return (60 * TPS) / gap;
}

/** Flags held by each side (and unowned) at `tick`. */
export function flagCounts(tick) {
  const n = { 0: 0, 1: 0, 2: 0 };
  for (const cp of M.doc.control_points) { const t = histAt(cp.history, tick, cp.initial_team); n[t === 1 || t === 2 ? t : 0]++; }
  return n;
}

/** The round running at `tick`: `{ start, end }` (end 0 = no time limit). */
export function roundAt(tick) {
  let r = null;
  for (const x of M.doc.rounds || []) if (x.t <= tick) r = x;
  return r ? { start: r.t, end: r.end } : { start: M.tMin, end: 0 };
}

const rowAt = (hist, tick) => { if (!hist || !hist.length) return null; let lo = 0, hi = hist.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (hist[m][0] <= tick) { r = m; lo = m + 1; } else hi = m - 1; } return r < 0 ? null : hist[r]; };

/** One scoreboard row of a player at `tick`: what the game's own PlayerScoreData held then. */
export function statsAt(p, tick) {
  const st = rowAt(p.stats_history, tick), sc = rowAt(p.score_history, tick);
  return { score: sc ? sc[1] : 0, kills: st ? st[1] : 0, deaths: st ? st[2] : 0, teamwork: st ? st[3] : 0, teamkills: st ? st[4] : 0 };
}
export const isPresent = (p, tick) => tick >= p.join_tick && (p.leave_tick == null || tick <= p.leave_tick);

/**
 * The weapon a player holds at `tick`: the soldier's `weapon_item_index` against the kit's slot table (`doc.kit_slots`, from the weapons' `itemIndex`).
 * Several names = the default weapon and its unlocks (which one the player picked is not recorded). `null` when unknown (in a vehicle, no update yet).
 */
export function heldWeapon(p, tick) {
  for (const tr of M.byOwner.get(p.player_id) || []) {
    if (tick < tr.t0 || tick > tr.tEnd || !tr.wt) continue;
    const i = bsearch(tr.wt, tick); if (i < 0) return null;
    const idx = tr.wv[i]; if (idx < 0) return { none: true };
    const kit = kitOf(p, tick), fac = (M.teamNames[teamOfPlayer(p, tick)] || "").toLowerCase();
    const slots = M.doc.kit_slots && kit != null ? M.doc.kit_slots[fac + "_" + String(M.kitNames[kit]).toLowerCase()] : null;
    const names = slots && slots[idx];
    return { names: names ? names.map((n) => (/^parachute/i.test(n) ? "Parachute" : n)) : null, idx };
  }
  return null;
}
