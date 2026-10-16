// UI state shared by the modules, and the redraw flag.
export const S = {
  tick: 0, playing: false, speed: 8,
  view: { cx: 0, cz: 0, zoom: 1 },
  sel: null, follow: false, hover: null, moments: [], persp: 1, iconScale: 1, rate: 1, hudScale: 0,
  teams: { 1: true, 2: true },
  kinds: { soldier: true, vehicle: true, empty: true, other: true },
  kits: {}, squad: "all", color: "team",
  layers: { names: true, cps: true, lines: false, heat: false, trail: true, corpses: true, strikes: true, hd: true },
};

let dirty = true;
export const invalidate = () => { dirty = true; };
export const takeDirty = () => { const d = dirty; dirty = false; return d; };

export const resetFilters = () => {
  S.teams = { 1: true, 2: true }; S.kinds = { soldier: true, vehicle: true, empty: true, other: true }; S.kits = {}; S.squad = "all"; S.color = "team";
  S.layers = { names: true, cps: true, lines: false, heat: false, trail: true, corpses: true, strikes: true, hd: true };
};
