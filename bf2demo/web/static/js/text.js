// Turns the parser's technical log lines into plain sentences: internal ids (CPNAME_..., us_light_soldier, tick numbers) are
// replaced by the names the game shows, or by a readable fallback. Only the viewer does this; the exports keep the raw ids.
import { names, vehicleInfo } from "./assets.js";

const CP_TOKEN = /\b(?:cpname_[a-z0-9]+_\d+_[a-z0-9_]+|\d+_(?:ch|us|mec|eu)_cp_[a-z0-9_]+)\b/gi;
const prettify = (s) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** "CPNAME_DP_64_reactors" -> "Reactor Towers" (the game's string) or "Reactors"; "64_CH_CP_Beach" -> "Beach". */
export function cpDisplayName(template) {
  const known = names[(template || "").toLowerCase()];
  if (known) return known;
  const m = (template || "").match(/^cpname_[a-z0-9]+_\d+_(.+)$/i) || (template || "").match(/^\d+_[a-z]+_cp_(.+)$/i);
  return prettify(m ? m[1] : template || "");
}

export const cpTokens = (texts) => {
  const found = new Set();
  for (const t of texts) for (const m of t.match(CP_TOKEN) || []) found.add(m);
  return [...found];
};

/** Display name of a vehicle template: the game's name, else the template id without its faction prefix. */
export function vehicleLabel(template) {
  const info = vehicleInfo(template);
  return info && info.name ? info.name : prettify(template.replace(/^(?:us|ch|mec|eu|usa|ahe|usthe|chthe|jep|jeep|apc|air|tnk|ustnk|usapc|usair|chair)_/i, ""));
}

const RULES = [
  [/ has joined the game \(already connected when the recording began\)/, " was already in the game"],
  [/Round began \(no time limit\)/, "Round started"],
  [/Round began \(scheduled end at tick \d+, ([\d:]+) later\)/, "Round started (time limit $1)"],
  [/ died \(no killer player\)\s+\(not shown in the game HUD\)/, " died"],
  [/ \((?:us|ch|mec|eu)_\w+_soldier\)/g, ""],
  [/ spotted object #\d+ at x=-?\d+ z=-?\d+/, " spotted an enemy"],
  [/ spotted (\w+) #\d+ at x=-?\d+ z=-?\d+/, (_, t) => " spotted " + vehicleLabel(t)],
  [/ \(object #\d+\)/, ""],
  [/ starts as (\w+)$/, " - held by $1 at the start"],
  [/^(\w+) team captured a control point \((.+?)\) - score at this tick: (.*)$/, "$1 captured $2 ($3)"],
  [/^(\w+) team captured a control point \((.+?)\)$/, "$1 captured $2"],
  [/^(.+?) was neutralized - score at this tick: (.*)$/, "$1 was neutralized ($2)"],
  [/ entered (\w+)$/, (_, t) => " entered " + vehicleLabel(t)],
];

/** Readable text of a feed line (control point names must already be resolved through `cpDisplayName`). */
export function friendlyText(text) {
  let out = text.replace(CP_TOKEN, (t) => cpDisplayName(t));
  for (const [re, to] of RULES) out = out.replace(re, to);
  return out;
}

/** Lines that only describe a soldier spawning (`X entered us_light_soldier`) say nothing a viewer can use. */
export const isNoise = (f) => f.kind === "vehicle" && /_soldier$/i.test(f.text);
