// Colours shared by the map and the panels. The game colours markers relative to the viewer: the viewer's own side is blue, the enemy red
// and the viewer's own squad green (BF2.exe minimap colour tables: friend (0.254, 0.552, 0.89), enemy (0.922, 0.208, 0.208), squad (0, 1, 0)).
export const FRIEND = "#418CE3", ENEMY = "#EB3636", SQUAD = "#00FF00";
export const TEAM_COL = { 0: "#9aa5b1", 1: ENEMY, 2: FRIEND };
export const KIT_COL = ["#b388ff", "#7bd88f", "#ff9f43", "#ffd166", "#4dd0e1", "#ff7aa2", "#c0ca33"];
export const squadColor = (s) => (s > 0 ? `hsl(${(s * 47) % 360} 80% 62%)` : "#9aa5b1");

/** The side we look from: its markers are blue, the other side's red (mutates TEAM_COL, which every module reads). */
export function setPerspective(team) {
  TEAM_COL[1] = team === 1 ? FRIEND : ENEMY;
  TEAM_COL[2] = team === 2 ? FRIEND : ENEMY;
}
