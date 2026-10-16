// The game's top bar (HudElementsMap.con, 800 x 600 layout): round time, both ticket counters in the bitmap digit font, flags and flag bars.
// Text nodes are aligned as the game aligns them (alignment code 1 = right: the digits end at the right edge of their node), the glyphs are
// smoothed like the game's filtered quads. The counter of a team that bleeds tickets to the flags pulses as in the game: its alpha runs up and
// down linearly between invisible and full once every 1.03 s (measured on a game video: peaks every 31 frames at 30 fps).
import { plain, spriteRect } from "./assets.js";
import { dpr, hudKSmall } from "./hudscale.js";
import { drawIn, drawText, hasFont } from "./font.js";
import { M, bleedRate, flagCounts, roundAt, ticketsAt } from "./model.js";
import { TEAM_COL } from "./palette.js";
import { S } from "./state.js";
import { $, TPS } from "./util.js";

const TEX = {
  time: "ingame/bars/timebarbackground", frame: "ingame/minimap/map_frameopen", blue: "ingame/minimap/teampoint_blueleft", red: "ingame/minimap/teampoint_redright",
  capL: "ingame/minimap/flags_frameopen_captured_left", capR: "ingame/minimap/flags_frameopen_captured_right",
};
const X0 = 522, W = 796 - 522, H = 16, DIGITS = "digitalNumbers";
const TIME_COLOR = "#C8CCB1", FRIEND_DIGITS = "#96E0FF", ENEMY_DIGITS = "#FFB0B4", NEUTRAL = "#838383", PULSE_SECONDS = 1.03;
const FLAG = { US: "us", CH: "ch", MEC: "mec", EU: "eu" };

/** True while a counter pulses: the page then redraws the bar every frame instead of at 4 Hz. */
export let animating = false;

const clock = (sec) => { sec = Math.max(0, Math.floor(sec)); return String(Math.floor(sec / 60)).padStart(2, "0") + ":" + String(sec % 60).padStart(2, "0"); };
/** Linear 0 -> 1 -> 0 ramp of the game's bleed pulse. */
const pulse = (now) => { const f = ((now / 1000) / PULSE_SECONDS) % 1; return 1 - Math.abs(2 * f - 1); };

export function drawHudBar(tick) {
  const cv = $("hudbar"), area = $("mapWrap").getBoundingClientRect(), scale = hudKSmall(area.width, area.height);
  const w = Math.ceil(W * scale), h = Math.ceil((H + 26) * scale);
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  cv.style.width = w / dpr() + "px"; cv.style.height = h / dpr() + "px";
  const g = cv.getContext("2d");
  g.clearRect(0, 0, w, h); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
  const at = (x) => (x - X0) * scale;
  const img = (key, x, y, dw, dh) => { const i = plain(key); if (i) g.drawImage(i, at(x), y * scale, (dw || i.width) * scale, (dh || i.height) * scale); return !!i; };
  const friendly = S.persp, enemy = 3 - S.persp, fCol = TEAM_COL[friendly], eCol = TEAM_COL[enemy];
  const round = roundAt(tick), remaining = round.end > 0 ? (round.end - tick) / TPS : (tick - round.start) / TPS;
  const haveArt = img(TEX.time, 522, 0);
  img(TEX.frame, 596, 0); img(TEX.blue, 605, 0); img(TEX.red, 738, 0);
  if (!haveArt) { g.fillStyle = "rgba(10,14,20,.8)"; g.fillRect(0, 0, w, H * scale); }

  const text = (str, x, width, y, color, alpha = 1) => {
    g.globalAlpha = alpha;
    if (hasFont(DIGITS)) drawIn(g, DIGITS, str, at(x), y * scale, width, "right", color, scale, false);
    else { g.fillStyle = color; g.font = `${9 * scale}px monospace`; g.textAlign = "right"; g.fillText(str, at(x + width), (y + 9) * scale); g.textAlign = "left"; }
    g.globalAlpha = 1;
  };
  text(clock(remaining), 527, 70, 3, TIME_COLOR);                       // TimeHour: x 528, width 70 (the game draws 1 px left of and below the node origin, measured on its video)

  const f = ticketsAt(friendly, tick), e = ticketsAt(enemy, tick), fb = bleedRate(friendly, tick), eb = bleedRate(enemy, tick);
  const wave = pulse(performance.now());
  text(f == null ? "-" : String(f), 611, 27, 3, FRIEND_DIGITS, fb ? wave : 1);        // FriendlyTickets: x 612, width 27
  text(e == null ? "-" : String(e), 755, 27, 3, ENEMY_DIGITS, eb ? wave : 1);         // EnemyTickets: x 756, width 27
  animating = !!(fb || eb);

  // team flags under the ticket boxes (FriendlyTeamFlag 602,20 / EnemyTeamFlag 772,20, 18 x 12)
  const flagOf = (team) => "ingame/flags/icons/hud/score/" + (FLAG[(M.teamNames && M.teamNames[team]) || ""] || "us") + "/scoreboard_flag";
  img(flagOf(friendly), 602, 20, 18, 12); img(flagOf(enemy), 772, 20, 18, 12);

  // flag bars: one dash per flag held, growing inwards from the side's own end in its colour; unowned flags are grey dashes after them
  const n = flagCounts(tick), DASH = 4, MAX = 10;
  const dashes = (key, color, fromRight, count) => {
    count = Math.min(MAX, count);
    const px = count * DASH * scale, sprite = spriteRect(key, color, 78 * scale, 6 * scale);
    if (!sprite || px <= 0) return;
    const sx = fromRight ? 78 * scale - px : 0;
    g.drawImage(sprite, sx, 0, px, 6 * scale, at(fromRight ? 736 - px / scale : 658), 6 * scale, px, 6 * scale);
  };
  dashes(TEX.capL, NEUTRAL, false, n[friendly] + n[0]); dashes(TEX.capL, fCol, false, n[friendly]);
  dashes(TEX.capR, NEUTRAL, true, n[enemy] + n[0]); dashes(TEX.capR, eCol, true, n[enemy]);

  // the loss in tickets per minute under the number of the team that is bleeding
  const rate = (value, x, color) => { if (value) drawText(g, "ingameChatFontLocalOutline_8", "-" + value.toFixed(1) + "/min", at(x), (H + 13) * scale, color, scale); };
  if (hasFont("ingameChatFontLocalOutline_8")) { rate(fb, 624, fCol); rate(eb, 758, eCol); }
}
