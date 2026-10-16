// The game's kill message ("game log"): colours measured on game screenshots and the message formats of the game's own strings.
//   killer / victim names and the bracket: the line colour = the relation of the KILLER to the viewed side (own side blue, enemy red, a
//   commander yellow for both); the weapon's name and the closing bracket: orange; the quoted class of a weapon ('Carbine', 'ATGM'): line colour.
import { A } from "./assets.js";
import { hasFont, lineCanvas } from "./font.js";
import { dpr, hudKSmall } from "./hudscale.js";
import { M, isCommander, teamOfPlayer } from "./model.js";
import { S } from "./state.js";
import { el, esc } from "./util.js";

export const LOG = { friend: "#03B6F0", enemy: "#FC6363", commander: "#F5D141", orange: "#FBA22B" };
export const LOG_FONT = "ingameChatFontLocalOutline_8";
const FEED_SIZE = 1.2;                    // the live feed is drawn a little larger than the game's own layout size (user request)

/** Blue when the killer is on the viewed side, red otherwise (a commander's name stays yellow, the words around it do not). */
export function sideColor(k) {
  const who = M.players.get(k.k);
  return who && teamOfPlayer(who, k.tick) === S.persp ? LOG.friend : LOG.enemy;
}

/** Colour of a whole message: by the killer (or the player himself in a suicide). */
export function lineColor(k) {
  const who = M.players.get(k.k);
  if (who && isCommander(who, k.tick)) return LOG.commander;
  return who && teamOfPlayer(who, k.tick) === S.persp ? LOG.friend : LOG.enemy;
}

const nameOf = (id) => { const p = M.players.get(id); return p ? p.name.trim() : "?"; };

/** Split a weapon text `M4A1 'Carbine'` into its model (orange) and its quoted class (line colour). */
function weaponParts(text) {
  const q = text.indexOf("'");
  return q < 0 ? [text, ""] : [text.slice(0, q), text.slice(q)];
}

/** Expand a game format (`#PLAYERNAME1# [#WEAPON#] #PLAYERNAME2#`) into coloured runs; `parts` maps a token to runs, the rest takes `color`. */
function expand(format, parts, color) {
  const runs = [];
  for (const piece of format.split(/(#[A-Z0-9]+#)/)) {
    if (!piece) continue;
    const key = piece.slice(1, -1);
    if (piece.startsWith("#") && parts[key]) runs.push(...parts[key]); else runs.push({ t: piece, c: color });
  }
  return runs;
}

const FORMAT = {
  kills: "#PLAYERNAME1# [#WEAPON#] #PLAYERNAME2#",
  teamkills: "#PLAYERNAME1# [TeamKills - #WEAPON#] #PLAYERNAME2#",
  killed: "#PLAYERNAME1# [Killed] #PLAYERNAME2#",
  myself: "#PLAYERNAME# is no more.",
};
const fmt = (key) => (A.strings["hud_hud_killedby_" + key] || FORMAT[key]).replace(/^\s+|\s+$/g, "");

/** The coloured runs `[{t, c}]` of a kill-feed entry (`M.logKills`). */
export function killRuns(k) {
  const L = lineColor(k), O = LOG.orange;
  if (k.k === k.v) return expand(fmt("myself"), { PLAYERNAME: [{ t: nameOf(k.v), c: L }] }, sideColor(k));      // "is no more.": red or blue by the player's side
  const a = [{ t: nameOf(k.k), c: L }], b = [{ t: nameOf(k.v), c: L }];
  const weapon = k.w == null ? "" : k.w;
  if (k.tk) return expand(fmt("teamkills"), { PLAYERNAME1: a, PLAYERNAME2: b, WEAPON: [{ t: weapon, c: L }] }, L);
  if (k.noWeapon) {                                           // the game's "[Killed]": the word is orange, so is the closing bracket
    const word = (fmt("killed").match(/\[(.*?)\]/) || [0, "Killed"])[1];
    return closeBracket(expand("#PLAYERNAME1# [#WEAPON#] #PLAYERNAME2#", { PLAYERNAME1: a, PLAYERNAME2: b, WEAPON: [{ t: word, c: O }] }, L), O);
  }
  const [model, cls] = weaponParts(weapon);
  return closeBracket(expand(fmt("kills"), { PLAYERNAME1: a, PLAYERNAME2: b, WEAPON: [{ t: model, c: O }, { t: cls, c: L }] }, L), O);
}

/** The bracket that closes the weapon takes the weapon colour (the one run that starts with "]"). */
function closeBracket(runs, color) {
  const i = runs.findIndex((r) => r.t.startsWith("]"));
  if (i < 0) return runs;
  const rest = runs[i].t.slice(1);
  return [...runs.slice(0, i), { t: "]", c: color }, ...(rest ? [{ t: rest, c: runs[i].c }] : []), ...runs.slice(i + 1)];
}

/** One DOM line: the game's bitmap font on a canvas when it is available, plain outlined HTML otherwise. */
export function killNode(k) {
  const runs = killRuns(k).filter((r) => r.t);
  const area = document.getElementById("mapWrap").getBoundingClientRect(), scale = hudKSmall(area.width, area.height) * FEED_SIZE;
  const canvas = hasFont(LOG_FONT) ? lineCanvas(LOG_FONT, runs, scale) : null;
  if (canvas) { canvas.className = "kcanvas"; canvas.style.width = canvas.width / dpr() + "px"; canvas.style.height = canvas.height / dpr() + "px"; return canvas; }
  return el("div", "kline", runs.map((r) => `<span style="color:${r.c}">${esc(r.t)}</span>`).join(""));
}

/** HTML of a kill line for lists (the log tab). */
export function killHTML(k) {
  return killRuns(k).map((r) => `<span style="color:${r.c}">${esc(r.t)}</span>`).join("");
}
