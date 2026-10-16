"""Several recordings of the same map as one :class:`~bf2demo.replay.Replay` for ``--export-con``.

A single demo seldom shows every spawn point (a soldier must spawn twice at the identical position) or every vehicle respawn (an
exact spawner position needs a vehicle created during the recording). More recordings of the same map add evidence; they never
contradict it. The merged replay is the first demo with

* the kit spawns of every demo (the same exact position repeated across demos now counts as repeated),
* the vehicle spawners of every demo merged by transform (an exact site absorbs the snapshot-only sites of the same vehicle),
* each control point's owner history continued in time: later demos are shifted behind the earlier ones, so a spawner observation of
  demo B is resolved with the owner of its flag *in demo B*,
* the spawn groups of every demo.

Everything else (map-load snapshot reasoning, the player list, tracks) stays the first demo's. All demos must show the same
level, mode and size.
"""

from __future__ import annotations

import copy
from typing import Dict, List, Sequence, Tuple

from .replay import (SNAPSHOT_MATCH_RADIUS, ControlPointState, GameObject, KitSpawn, Replay, SpawnSite, _dist,
                     _transform_key)

#: gap, in ticks, between two demos on the shared time line (larger than any tick of a state change)
_GAP = 1000


def _check_same_map(replays: Sequence[Replay]) -> None:
    first = replays[0]
    key = (first.level, first.game_mode, first.map_size)
    for other in replays[1:]:
        if (other.level, other.game_mode, other.map_size) != key:
            raise ValueError(f"cannot merge {other.level} {other.game_mode}/{other.map_size} into {first.level} "
                             f"{first.game_mode}/{first.map_size}: the recordings must show the same map")


def _merge_control_points(replays: Sequence[Replay], offsets: Sequence[int]) -> Dict[int, ControlPointState]:
    merged = {oid: copy.copy(cp) for oid, cp in replays[0].control_points.items()}
    for cp in merged.values():
        cp.history = list(cp.history)
    by_name = {cp.template.name: cp for cp in merged.values() if cp.template}
    for replay, offset in list(zip(replays, offsets))[1:]:
        for cp in replay.control_points.values():
            target = by_name.get(cp.template.name) if cp.template else None
            if target is not None:
                # before this demo's first flag event its own initial owner holds (not the last owner of the previous demo)
                if cp.initial_team is not None:
                    target.history.append((offset - _GAP // 2, cp.initial_team))
                target.history.extend((tick + offset, team) for tick, team in cp.history)
    return merged


def _shift(site: SpawnSite, offset: int) -> SpawnSite:
    out = copy.copy(site)
    out.templates = dict(site.templates)
    out.snapshot_templates = list(site.snapshot_templates)
    out.observations = [(tick + offset, template, team, snap) for tick, template, team, snap in site.observations]
    out.first_tick = site.first_tick + offset
    return out


def _absorb(into: SpawnSite, other: SpawnSite) -> None:
    for name, count in other.templates.items():
        into.templates[name] = into.templates.get(name, 0) + count
    into.snapshot_templates.extend(other.snapshot_templates)
    into.observations.extend(other.observations)
    into.first_tick = min(into.first_tick, other.first_tick)


def _merge_sites(replays: Sequence[Replay], offsets: Sequence[int], cps: Dict[int, ControlPointState]) -> List[SpawnSite]:
    sites = [_shift(site, offset) for replay, offset in zip(replays, offsets) for site in replay.spawn_sites]
    exact: Dict[tuple, SpawnSite] = {}
    for site in (s for s in sites if s.exact):
        key = _transform_key(site.position, site.rotation)
        if key in exact:
            _absorb(exact[key], site)
        else:
            exact[key] = site
    loose: List[SpawnSite] = []
    for site in (s for s in sites if not s.exact):
        names = {n for n in site.snapshot_templates}
        home = [e for e in exact.values() if names & set(e.templates) and _dist(e.position, site.position) <= SNAPSHOT_MATCH_RADIUS]
        if home:
            _absorb(min(home, key=lambda e: _dist(e.position, site.position)), site)
            continue
        twin = next((o for o in loose if _dist(o.position, site.position) <= 0.01 and set(o.snapshot_templates) == names), None)
        if twin is not None:
            _absorb(twin, site)
        else:
            loose.append(site)
    ordered = list(exact.values()) + loose
    flags = [cp for cp in cps.values() if cp.position]
    for site in ordered:
        if flags:
            cp = min(flags, key=lambda c: _dist(c.position, site.position))
            site.nearest_cp, site.nearest_cp_distance = cp, _dist(cp.position, site.position)
    ordered.sort(key=lambda s: (s.nearest_cp.object_id if s.nearest_cp else 0, not s.exact, s.first_tick))
    return ordered


def merge_replays(replays: Sequence[Replay]) -> Replay:
    """The first replay enriched with the evidence of the others (see the module documentation)."""
    if not replays:
        raise ValueError("nothing to merge")
    _check_same_map(replays)
    if len(replays) == 1:
        return replays[0]
    offsets = [0]
    for replay in replays[:-1]:
        offsets.append(offsets[-1] + (replay.last_tick or 0) + _GAP)
    merged = copy.copy(replays[0])
    merged.control_points = _merge_control_points(replays, offsets)
    merged.spawn_sites = _merge_sites(replays, offsets, merged.control_points)
    merged.kit_spawns = [KitSpawn(k.tick + off, k.position, k.object_id, k.kit_template_id, k.kit_id)
                         for replay, off in zip(replays, offsets) for k in replay.kit_spawns]
    merged.events = list(replays[0].events) + [
        (tick + off, ev) for replay, off in list(zip(replays, offsets))[1:] for tick, ev in replay.events
        if ev.name in ("CreateSpawnGroup", "RemoveSpawnGroup")]
    merged.merged_from = [r.demo.header.recorded_at for r in replays]
    return merged
