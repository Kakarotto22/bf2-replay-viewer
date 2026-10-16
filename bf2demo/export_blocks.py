"""Text helpers and block builders of the ``GamePlayObjects.con`` exporter (retail style)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional

from .export_observe import DemoCP, DemoSpawner
from .layouts import Item

NEW_SPAWN_OFFSET_Y = 1.25              # offset written for spawn points that are new
DEFAULT_AUTHOR = '"bf2demo"'
HEADER = re.compile(r"^rem \*{10} (Object Spawner|Spawn Points|Control Points) \*{10}$")

#: The dedicated server's console parser stops loading the map ("hangs at 14%") on very long lines: the longest line in any retail
#: GamePlayObjects.con is 93 characters, and a 2205 character ``rem`` line in the notes block reproduced the hang. Notes are wrapped.
MAX_LINE = 100


def wrap_rem(text: str, width: int = MAX_LINE) -> List[str]:
    """``rem`` comment lines of at most ``width`` characters (continuation lines are indented by three spaces)."""
    lines, current = [], ""
    for word in text.split(" "):
        candidate = word if not current else current + " " + word
        if len(candidate) > width and current:
            lines.append(current)
            current = "rem   " + word
        else:
            current = candidate
    lines.append(current)
    return lines


def fmt(v: float) -> str:
    text = f"{v:.3f}"
    return "0.000" if text == "-0.000" else text


def vec(v) -> str:
    return "/".join(fmt(c) for c in v)


def expand(items: List[Item]) -> List[Item]:
    """Split static text into one item per line so anchors can be located exactly."""
    out: List[Item] = []
    for it in items:
        if it.is_block:
            out.append(it)
        else:
            out.extend(Item([line]) for line in it.lines)
    return out


def slots_of(item: Item) -> Dict[int, str]:
    out = {}
    for line in item.lines:
        m = re.match(r"^\s*ObjectTemplate\.setObjectTemplate\s+(\d+)\s+(\S+)", line, re.I)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def replace_prop(lines: List[str], key: str, value: str) -> bool:
    pat = re.compile(rf"^(\s*)(Object(?:Template)?\.{key})\s+.*$", re.I)
    for i, line in enumerate(lines):
        m = pat.match(line)
        if m:
            lines[i] = f"{m.group(1)}{m.group(2)} {value}"
            return True
    return False


def _same_rotation(line: str, rotation) -> bool:
    """True when an existing ``Object.rotation`` line already says the same thing (yaw mod 360)."""
    m = re.search(r"Object\.rotation\s+(\S+)", line, re.I)
    if not m:
        return False
    try:
        old = [float(v) for v in m.group(1).split("/")]
    except ValueError:
        return False
    if len(old) != 3 or abs(((old[0] - rotation[0]) + 180.0) % 360.0 - 180.0) > 0.0015:
        return False
    return all(abs(a - b) <= 0.0015 for a, b in zip(old[1:], rotation[1:]))


def set_rotation(lines: List[str], rotation) -> None:
    for line in lines:
        if re.match(r"^\s*Object\.rotation\s", line, re.I) and _same_rotation(line, rotation):
            return
    replace_prop(lines, "rotation", vec(rotation))


def insert_before_trailing_blank(lines: List[str], new: str) -> None:
    pos = len(lines)
    while pos > 0 and lines[pos - 1].strip() == "":
        pos -= 1
    lines.insert(pos, new)


def majority(values, default):
    values = [v for v in values if v]
    return Counter(values).most_common(1)[0][0] if values else default


# --------------------------------------------------------------------------- #
# New instances of templates the layout already has (the client-compatible way)
# --------------------------------------------------------------------------- #

def duplicate_instance(source: Item, position, rotation: Optional[tuple] = None, control_point_id: Optional[str] = None) -> Item:
    """Another instance of the same template: a copy of ``source`` at a new transform.

    A template is created once; creating one more *object* from it changes no template id, so a client that has the original
    map files still numbers the templates like the server does.
    """
    lines = list(source.lines)
    replace_prop(lines, "absolutePosition", vec(position))
    if rotation is not None:
        replace_prop(lines, "rotation", vec(rotation))
    if control_point_id is not None:
        replace_prop(lines, "setControlPointId", str(control_point_id))
    return Item(lines, source.cls, False, source.name)


# --------------------------------------------------------------------------- #
# Blocks for objects the layout does not describe (these create NEW templates)
# --------------------------------------------------------------------------- #

def new_spawner_template(name, ds: DemoSpawner, author) -> List[str]:
    lines = [f"rem [ObjectSpawnerTemplate: {name}]",
             f"ObjectTemplate.create ObjectSpawner {name}",
             f"ObjectTemplate.activeSafe ObjectSpawner {name}",
             f"ObjectTemplate.modifiedByUser {author}",
             "ObjectTemplate.isNotSaveable 1",
             "ObjectTemplate.hasMobilePhysics 0"]
    lines += [f"ObjectTemplate.setObjectTemplate {slot} {tpl}" for slot, tpl in sorted(ds.template_slots.items())]
    if ds.team_on_vehicle:
        lines.append("ObjectTemplate.teamOnVehicle 1")
    return lines + [""]


def new_spawner_instance(name, ds: DemoSpawner, cp_id, layer) -> List[str]:
    return [f"   rem [ObjectSpawner: {name}]", f"   Object.create {name}",
            f"   Object.absolutePosition {vec(ds.position)}",
            f"   Object.rotation {vec(ds.rotation)}",
            f"   Object.setControlPointId {cp_id}", f"   Object.layer {layer}", ""]


def new_point_blocks(name, position, author, cp_id, layer):
    tpl = [f"rem [SpawnPointTemplate: {name}]", f"ObjectTemplate.create SpawnPoint {name}",
           f"ObjectTemplate.activeSafe SpawnPoint {name}", f"ObjectTemplate.modifiedByUser {author}",
           "ObjectTemplate.isNotSaveable 1",
           f"ObjectTemplate.setSpawnPositionOffset 0/{NEW_SPAWN_OFFSET_Y:g}/0",
           f"ObjectTemplate.setControlPointId {cp_id}", ""]
    pos = (position[0], position[1] - NEW_SPAWN_OFFSET_Y, position[2])
    inst = [f"rem [SpawnPoint: {name}]", f"Object.create {name}",
            f"Object.absolutePosition {vec(pos)}", "Object.rotation 0.000/0.000/0.000",
            f"Object.layer {layer}", ""]
    return tpl, inst


def new_cp_blocks(dc: DemoCP, author, cp_id, layer):
    n = dc.name
    tpl = [f"rem [ControlPointTemplate: {n}]", f"ObjectTemplate.create ControlPoint {n}",
           f"ObjectTemplate.activeSafe ControlPoint {n}", f"ObjectTemplate.modifiedByUser {author}",
           "ObjectTemplate.setNetworkableInfo ControlPointInfo", "ObjectTemplate.isNotSaveable 1",
           "ObjectTemplate.hasMobilePhysics 0", "ObjectTemplate.hasCollisionPhysics 1",
           "ObjectTemplate.physicsType Mesh", "rem -------------------------------------",
           "ObjectTemplate.addTemplate flagpole", "rem -------------------------------------",
           f"ObjectTemplate.setControlPointName {n}", "ObjectTemplate.radius 10"]
    if dc.team:
        tpl.append(f"ObjectTemplate.team {dc.team}")
    tpl += [f"ObjectTemplate.controlPointId {cp_id}", "ObjectTemplate.areaValueTeam1 35",
            "ObjectTemplate.areaValueTeam2 35", "ObjectTemplate.timeToGetControl 20",
            "ObjectTemplate.timeToLoseControl 20", "ObjectTemplate.hoistMinMax 0.2/0.9", ""]
    inst = [f"   rem [ControlPoint: {n}]", f"   Object.create {n}",
            f"   Object.absolutePosition {vec(dc.position)}", f"   Object.layer {layer}", ""]
    return tpl, inst
