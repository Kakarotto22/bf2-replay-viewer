"""What a demo shows about the gameplay objects of a level (the input of :mod:`bf2demo.export_con`)."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .replay import ControlPointState, Replay, SpawnSite
from .settle import settle_offset

Vec3 = Tuple[float, float, float]

MATCH_RADIUS = 3.0                     # layout position hint for spawners / control points
MATCH_XZ = 0.0015                      # spawn points: exact X/Z
LATE_RECORDING_TICK = 300              # a snapshot taken later than this is not the map-load state
#: absence is only concluded from a snapshot up to this tick (30 s after load): nobody can have destroyed a vehicle before that
ABSENCE_MAX_TICK = 900


@dataclass
class ExportOptions:
    min_spawn_count: int = 2
    layer: Optional[int] = None                # only used for objects the layout cannot describe
    author: Optional[str] = None               # raw text after modifiedByUser for new objects
    cp_ids: Optional[List[int]] = None         # controlPointId per control point (no-layout mode)
    include_single: bool = False               # also export one-off vehicles (drops look like this)
    layout: Optional[str] = None               # explicit layout text (e.g. a reference file)
    use_layout: bool = True                    # use the bundled retail layout when available
    keep_unobserved: bool = True               # keep layout objects that the demo never showed (unchanged)
    settle_estimate: bool = False              # opt-in: estimate the spawner Y of snapshot-only ground vehicles
    #: a spawner whose vehicle for the owner of its control point is missing from a map-load snapshot does not exist
    drop_absent_spawners: bool = True
    #: new object templates shift every later template id: a client that has the original map files then decodes the
    #: stream wrongly ("Networkable already added to network manager, netId=0"). Off: extra objects reuse a template.
    allow_new_templates: bool = False
    #: opt-in: a spawn group of the demo without any spawn point gets one placeholder point at its (quantised) centroid
    placeholder_spawns: bool = False


@dataclass
class DemoCP:
    state: ControlPointState
    name: str
    position: Vec3
    team: int


@dataclass
class DemoSpawner:
    site: SpawnSite
    cp: Optional[ControlPointState]
    slots: Dict[int, str]
    unknown_team: List[str]
    team_on_vehicle: bool
    position: Vec3
    rotation: Vec3
    note: Optional[str]
    estimated_dy: Optional[float] = None

    @property
    def observations(self) -> List[Tuple[int, str, int]]:
        """``(tick, vehicle, team field)`` of every creation seen at this site."""
        return [(tick, template, team) for tick, template, team, _ in self.site.observations]

    @property
    def reliable_slots(self) -> Dict[int, str]:
        """Slots known from the team of the created object itself (1 or 2); needs no control point."""
        out: Dict[int, str] = {}
        for _, template, team in self.observations:
            if team in (1, 2):
                out.setdefault(team, template)
        return out

    @property
    def vehicles(self) -> List[str]:
        """Every vehicle template this site produced, observed slot or not."""
        return list(dict.fromkeys(list(self.slots.values()) + self.unknown_team))

    @property
    def template_slots(self) -> Dict[int, str]:
        """Team slots to write for a spawner that gets a new template.

        A spawner seen only with team 0 at a still neutral control point has no observable team slot. Writing no
        ``setObjectTemplate`` at all gives a spawner without a vehicle, so the template goes to both team slots: whoever
        owns the point gets it.
        """
        if self.slots or not self.unknown_team:
            return self.slots
        return {1: self.unknown_team[0], 2: self.unknown_team[-1]}


@dataclass
class DemoPoint:
    position: Vec3            # final spawn position (kit position)
    count: int
    cp: Optional[ControlPointState]


def cp_team_at(cp: ControlPointState, tick: int) -> int:
    team = cp.initial_team if cp.initial_team is not None else 0
    for t, owner in cp.history:
        if t <= tick:
            team = owner
    return team


def _observation_slots(site: SpawnSite, cp: Optional[ControlPointState]):
    out = []
    for tick, template, team_field, _snapshot in site.observations:
        slot = team_field if team_field in (1, 2) else None
        if slot is None and cp is not None:
            owner = cp_team_at(cp, tick)
            slot = owner if owner in (1, 2) else None
        out.append((slot, template, team_field))
    return out


def _consistent(site: SpawnSite, cp: ControlPointState) -> bool:
    seen: Dict[str, set] = {}
    for slot, template, _ in _observation_slots(site, cp):
        if slot is None:
            return False
        seen.setdefault(template.lower(), set()).add(slot)
    if any(len(teams) != 1 for teams in seen.values()):
        return False
    owners = [next(iter(t)) for t in seen.values()]
    return len(owners) == len(set(owners))


def _bind_control_point(site: SpawnSite, cps: List[ControlPointState]) -> Optional[ControlPointState]:
    """Spawner -> control point (not on the wire): the nearest one, unless a site that produced
    several templates is only explained by another control point's ownership changes."""
    if not cps:
        return None
    ordered = sorted(cps, key=lambda cp: math.dist(cp.position, site.position))
    if len({o[1].lower() for o in site.observations}) > 1:
        for cp in ordered:
            if _consistent(site, cp):
                return cp
    return ordered[0]


def observe(replay: Replay, opt: ExportOptions):
    """``(control points, spawners, spawn points)`` the demo shows."""
    cps = [cp for cp in replay.control_points.values() if cp.position]
    demo_cps = [DemoCP(cp, cp.template.name, cp.position, cp.initial_team or 0) for cp in cps]
    spawners: List[DemoSpawner] = []
    for site in replay.spawn_sites:
        if not site.observations:
            continue
        if site.exact and not site.confirmed and not opt.include_single:
            continue
        cp = _bind_control_point(site, cps)
        slots: Dict[int, str] = {}
        unknown: List[str] = []
        team_on_vehicle = False
        for slot, template, team_field in _observation_slots(site, cp):
            team_on_vehicle = team_on_vehicle or team_field in (1, 2)
            if slot is None:
                if template not in unknown:
                    unknown.append(template)
            else:
                slots.setdefault(slot, template)
        note = None
        if not site.exact:
            note = ("mobile vehicle seen only in the join snapshot: Y/rotation approximate "
                    "(a recording that includes its respawn gives exact values)")
        elif not site.confirmed:
            note = "a single creation was observed at this transform (could be a one-off drop)"
        rotation = site.rotation if site.exact else (site.rotation[0], 0.0, 0.0)
        position = site.position
        estimated = None
        if not site.exact and opt.settle_estimate:
            estimated = settle_offset(site.observations[0][1])
            if estimated is not None:
                position = (position[0], position[1] - estimated, position[2])
                note = (f"mobile vehicle seen only in the join snapshot: Y estimated by subtracting the "
                        f"learned rest height {estimated:+.3f} (exact for most spawners on terrain)")
        spawners.append(DemoSpawner(site, cp, slots, unknown, team_on_vehicle, position, rotation, note, estimated))
    groups: Dict[Tuple[float, float], List[Vec3]] = {}
    for spawn in replay.kit_spawns:
        groups.setdefault((round(spawn.position[0], 3), round(spawn.position[2], 3)), []).append(spawn.position)
    points: List[DemoPoint] = []
    for (x, z), positions in groups.items():
        if len(positions) < opt.min_spawn_count:
            continue
        y = Counter(round(p[1], 3) for p in positions).most_common(1)[0][0]
        cp = min(cps, key=lambda c: math.hypot(c.position[0] - x, c.position[2] - z)) if cps else None
        points.append(DemoPoint((x, y, z), len(positions), cp))
    return demo_cps, spawners, points
