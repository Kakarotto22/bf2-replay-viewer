"""Spawn groups: the only information about spawn points a demo carries when nobody spawned.

A ``SpawnGroup`` is the set of ``SpawnPoint`` objects with the same ``(setControlPointId, setGroup)``. Its position is the
arithmetic mean of its points (``SpawnGroup::calcNewPos`` 0x08111540) and ``CreateSpawnGroupEvent`` sends it as two bytes
(``getUnsignedWorldPosition`` 0x08111840)::

    byte = int((size / 2 + coordinate) / size * 255)        size = the level's ``GLSWorldSize`` (:func:`world_size`)

Verified on 22 maps: for every level with a retail layout the group centroids computed from the layout equal the bytes of the
demo's groups exactly (106 of 106; Highway Tampa has no layout). A custom map whose centroids differ has other spawn points.
Groups with id 192 and above are squad spawn groups (always byte 127: no points) and are not described here.
"""

from __future__ import annotations

import collections
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Tuple

from .replay import Replay

_PATH = os.path.join(os.path.dirname(__file__), "assets", "world_sizes.json")
CONTROL_POINT_GROUP_LIMIT = 192          # ids below are per-control-point groups, ids from 192 on are squad groups

Cell = Tuple[int, int]


@lru_cache(maxsize=1)
def _sizes() -> Dict[str, int]:
    with open(_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)["sizes"]


def world_size(level: str) -> Optional[int]:
    """``GLSWorldSize`` of a level (``heightmapcluster.setHeightmapSize``), or None for an unknown level."""
    return _sizes().get((level or "").strip().lower())


def to_cell(coordinate: float, size: int) -> int:
    """The wire byte of a world coordinate (clamped to 0..255 like the engine)."""
    if coordinate > size / 2:
        return 255
    if coordinate < -size / 2:
        return 0
    return int((size / 2 + coordinate) / size * 255)


def cell_center(cell: int, size: int) -> float:
    """World coordinate in the middle of the area a byte stands for (the best single estimate of a centroid)."""
    return (cell + 0.5) / 255.0 * size - size / 2


@dataclass
class DemoSpawnGroup:
    group_id: int
    team: int
    cell: Cell
    object_id: int
    active: bool

    def center(self, size: int) -> Tuple[float, float]:
        return cell_center(self.cell[0], size), cell_center(self.cell[1], size)


def demo_groups(replay: Replay) -> List[DemoSpawnGroup]:
    """The per-control-point spawn groups announced by the demo (squad groups excluded)."""
    out, seen = [], set()
    for _, event in replay.events:
        if event.name == "CreateSpawnGroup" and event["spawn_group_id"] < CONTROL_POINT_GROUP_LIMIT:
            key = (event["spawn_group_id"], event["team"], event["map_x"], event["map_z"])
            if key in seen:                      # the same group announced again (a merged recording, a round restart)
                continue
            seen.add(key)
            out.append(DemoSpawnGroup(event["spawn_group_id"], event["team"], (event["map_x"], event["map_z"]),
                                      event["object_id"], bool(event["active"])))
    return out


def centroid_cell(positions: Iterable[Tuple[float, float, float]], size: int) -> Cell:
    """The byte pair of the mean x/z of a set of spawn points."""
    points = list(positions)
    return (to_cell(sum(p[0] for p in points) / len(points), size), to_cell(sum(p[2] for p in points) / len(points), size))


def group_by_key(points: Iterable[Tuple[object, Tuple[float, float, float]]]) -> Dict[object, List[Tuple[float, float, float]]]:
    """``{(control point id, group): [position]}`` from ``(key, position)`` pairs."""
    groups: Dict[object, List[Tuple[float, float, float]]] = collections.defaultdict(list)
    for key, position in points:
        groups[key].append(position)
    return dict(groups)
