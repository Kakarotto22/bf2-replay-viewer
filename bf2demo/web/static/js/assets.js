// In-game icons: fetched from the local server (which reads them from the player's own game install) and tinted on a canvas.
import { api } from "./util.js";

export const ICON = {
  soldier: "ingame/player/icons/minimap/mini_soldier",
  arrow: "ingame/player/icons/minimap/mini_headingarrow",
  uav: "ingame/minimap/icons/icon_uav",
  uavIcon: "ingame/minimap/icons/icon_uav",
  radar: "ingame/minimap/icons/radar",
  airDef: "ingame/vehicles/icons/minimap/mini_airdefsmall",
  armourDef: "ingame/vehicles/icons/minimap/mini_armourdefsmall",
  commander: "ingame/player/icons/minimap/mini_commander",
  commanderFriend: "ingame/player/icons/minimap/mini_commander2",   // blue disc with a star
  commanderEnemy: "ingame/player/icons/minimap/mini_commander1",    // red disc with a star
  localArrow: "ingame/player/icons/minimap/mini_localarrow2",      // the white view cone of the local player (50 x 70 px, apex at the bottom)
  uavSweep: "ingame/minimap/map_uav",                                 // 150 x 150, a gold quarter disc: the radar sweep, rotated about the image centre
  supplies: "ingame/minimap/icons/icon_supplies",
  vehicleDrop: "ingame/minimap/icons/icon_vehicledrop",
  ring: "ingame/minimap/icons/request_circle",                              // 58 px white ring around a supply drop
  artillery: "ingame/minimap/icons/icon_artillery",
  airstrike: "ingame/minimap/icons/placedairstrike",
};
const FACTION = { US: "us", CH: "ch", MEC: "mec", EU: "eu" };

export const A = { upload: true, installed: false, vehicles: {}, kits: {}, strings: {}, onLoad: () => {} };
const images = new Map();      // icon key -> HTMLImageElement | null (404)
const tinted = new Map();      // "key|color|px" -> canvas

export const names = {};                 // game string key (lower case) -> display text, e.g. cpname_dp_64_reactors -> Reactor Towers

/** One request for everything named: vehicle and kit icons / names and the control point and scoreboard strings (the server's own store). */
export async function loadAssets() {
  try {
    const game = (await api("/api/game")).json; A.installed = game.installed; A.upload = game.upload !== false;
    if (!A.installed) return;
    const table = (await api("/api/assets/tables")).json;
    A.vehicles = table.vehicles || {}; A.kits = table.kits || {}; A.strings = table.strings || {};
    for (const k in A.strings) names[k] = A.strings[k];
  } catch (e) { A.installed = false; }
}

export const iconUrl = (key) => "/api/hud/" + key + ".png";

function image(key) {
  if (images.has(key)) return images.get(key);
  const img = new Image();
  images.set(key, undefined);                                   // pending
  img.onload = () => { images.set(key, img); A.onLoad(); };
  img.onerror = () => images.set(key, null);
  img.src = iconUrl(key);
  return undefined;
}

/** Textures the HUD overlays draw (top bar, scoreboard, flags): loaded before the first frame so nothing pops in. */
export const HUD_TEXTURES = [
  "ingame/bars/timebarbackground", "ingame/minimap/map_frameopen", "ingame/minimap/teampoint_blueleft", "ingame/minimap/teampoint_redright",
  "ingame/minimap/flags_frameopen_captured_left", "ingame/minimap/flags_frameopen_captured_right",
  "ingame/scoreboard/team1_byscore", "ingame/scoreboard/team2_empty", "ingame/scoreboard/scoreboard_icons", "ingame/scoreboard/bottom",
  "ingame/scoreboard/staticinfobackground", "ingame/scoreboard/icons/icon_death", "ingame/scoreboard/icons/icon_faded",
  "ingame/scoreboard/icons/kickvote_no", "ingame/scoreboard/arrowdown",
  ...Array.from({ length: 22 }, (_, n) => "ingame/generalicons/ranks/rank_" + String(n).padStart(2, "0")),
  ...["us", "ch", "mec", "eu"].map((f) => "ingame/flags/icons/hud/score/" + f + "/scoreboard_flag"),
];
export function preload(keys) {
  return Promise.all(keys.filter((k) => !images.has(k)).map((key) => new Promise((ok) => {
    const img = new Image(); images.set(key, undefined);
    img.onload = () => { images.set(key, img); ok(); };
    img.onerror = () => { images.set(key, null); ok(); };
    img.src = iconUrl(key);
  })));
}


const crisp = new Map();       // icon key -> the texture enlarged by whole nearest-neighbour steps (see `crispSource`)
/**
 * The game has no larger version of its 16 - 64 px icons (one size per texture in every archive); it only stretches them with bilinear filtering.
 * To keep their edges sharp at any zoom, the texture is first enlarged by a whole factor with nearest neighbour (pixels stay square, nothing is
 * invented) and the page then resamples that large copy smoothly down to the wanted size ("sharp bilinear").
 */
function crispSource(key, img) {
  if (img.width > 64 || img.height > 128) return img;
  let c = crisp.get(key);
  if (!c) {
    const f = 8; c = document.createElement("canvas"); c.width = img.width * f; c.height = img.height * f;
    const g = c.getContext("2d"); g.imageSmoothingEnabled = false; g.drawImage(img, 0, 0, c.width, c.height);
    crisp.set(key, c);
  }
  return c;
}

/** A white-on-transparent game glyph recoloured and scaled to `px` device pixels (cached); null while loading or unavailable. */
export function sprite(key, color, px) {
  if (!A.installed || !key) return null;
  px = Math.round(px);
  const id = key + "|" + color + "|" + px, hit = tinted.get(id);
  if (hit) return hit;
  const img = image(key);
  if (!img) return null;
  const c = document.createElement("canvas"); c.width = c.height = px;
  const g = c.getContext("2d");
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
  const src = crispSource(key, img), s = px / Math.max(img.width, img.height);
  const dx = (px - img.width * s) / 2, dy = (px - img.height * s) / 2, dw = img.width * s, dh = img.height * s;
  g.drawImage(src, dx, dy, dw, dh);
  // multiply keeps the glyph's own dark parts (the game shows an outlined icon, not a flat silhouette); the alpha comes back afterwards
  g.globalCompositeOperation = "multiply"; g.fillStyle = color; g.fillRect(0, 0, px, px);
  g.globalCompositeOperation = "destination-in"; g.drawImage(src, dx, dy, dw, dh);
  tinted.set(id, c);
  return c;
}

/** Like `sprite` for a non-square texture drawn at `w` x `h` device pixels (the 16 x 64 leader overlays). */
export function spriteRect(key, color, w, h) {
  if (!A.installed || !key) return null;
  w = Math.round(w); h = Math.round(h);
  const id = key + "|" + color + "|" + w + "x" + h, hit = tinted.get(id);
  if (hit) return hit;
  const img = image(key);
  if (!img) return null;
  const src = crispSource(key, img), c = document.createElement("canvas"); c.width = w; c.height = h;
  const g = c.getContext("2d");
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
  g.drawImage(src, 0, 0, w, h);
  g.globalCompositeOperation = "multiply"; g.fillStyle = color; g.fillRect(0, 0, w, h);
  g.globalCompositeOperation = "destination-in"; g.drawImage(src, 0, 0, w, h);
  tinted.set(id, c);
  return c;
}

/** Untinted image (flags keep their own colours); null while loading. */
export function plain(key) { const img = A.installed ? image(key) : null; return img || null; }

/** Native size of a loaded texture (the game draws its minimap icons at their own pixel size); 16 until it has loaded. */
export function nativeSize(key) { const img = plain(key); return img ? Math.max(img.width, img.height) : 16; }

export const squadIconKey = (n) => "ingame/player/icons/minimap/mini_squad_" + Math.min(9, Math.max(0, n)) + "_small";

export function vehicleInfo(template) { return A.vehicles[template] || null; }

export function vehicleIconKey(template) {
  const info = A.vehicles[template];
  if (info && info.icon) return info.icon;
  const t = template.toLowerCase();                          // emplacements and buildings have no vehicle HUD entry
  if (/(igla|stinger|aas|sam|aa_)/.test(t)) return ICON.airDef;
  if (/(radar|tower)/.test(t)) return ICON.radar;
  if (/(ats|ars|bipod|tow|hj8|d30|lw155|wasp_def)/.test(t)) return ICON.armourDef;
  return ICON.armourDef;
}

/** The control point icon of the game's minimap: the flat flag of the owning faction (grey for neutral). `miniMap_Flag` is the waving
 *  variant used elsewhere, not on the minimap. */
export const flagKey = (teamCode, owned, base) => "ingame/flags/icons/minimap/" + (owned && FACTION[teamCode] ? FACTION[teamCode] : "neutral") + (base && owned && FACTION[teamCode] ? "/minimap_cpbase" : "/minimap_cp");

export function kitIcon(kitName) { return A.kits[(kitName || "").toLowerCase()] || null; }
