"""Recover the networked part of a level's ``StaticObjects.con`` from a demo.

Most static objects (houses, trees, sandbags ...) are never sent to a client, but the destructible ones are: wooden and stone
bridge segments, breakable crates and barrels, signs, doors made of planks, fuel wagons ... Each of them arrives in the join snapshot
as a ``CreateObjectEvent`` carrying its exact spawn transform (a static object has no physics, so the snapshot value is the file
value; verified to 3 decimals against the retail ``StaticObjects.con`` of Kubra Dam, see ``tests``).

A server-side custom map is mostly a changed ``StaticObjects.con`` / ``GamePlayObjects.con``, so this is the counterpart of
:mod:`bf2demo.export_con` for the static part. What the demo does not carry: the object layer (written as 1, the layer of 99.4%
of the retail objects), ``setLightSourceMask`` / ``isOvergrowth`` / ``group`` lines, and objects that were never networked.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from .replay import GameObject, Replay

#: template classes that a StaticObjects.con object can have and that cross the wire
STATIC_CLASSES = ("DestroyableObject", "SimpleObject")


def _number(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}"
    return text[1:] if text.startswith("-") and float(text) == 0.0 else text      # no "-0.000"


def _vector(value, decimals: int) -> str:
    return "/".join(_number(c, decimals) for c in value)


def static_objects(replay: Replay) -> List[GameObject]:
    """Networked static objects in creation order (object id order of the join snapshot)."""
    found = [o for o in replay.object_history
             if o.template is not None and o.template.cls in STATIC_CLASSES and o.position is not None and o.snapshot]
    return sorted(found, key=lambda o: o.object_id)


def moving_statics(objects: Iterable[GameObject]) -> List[GameObject]:
    """Statics whose template has physics: a snapshot taken after the round started may show them displaced."""
    return [o for o in objects if o.template.mobile]


def block(obj: GameObject, layer: int = 1) -> List[str]:
    """The ``StaticObjects.con`` lines of one object (retail style)."""
    lines = [f"rem *** {obj.template.name} ***", f"Object.create {obj.template.name}",
             f"Object.absolutePosition {_vector(obj.position, 3)}"]
    rotation = obj.rotation
    if rotation is not None and any(abs(round(c, 1)) > 0.0 for c in rotation):
        lines.append(f"Object.rotation {_vector(rotation, 1)}")
    lines.append(f"Object.layer {layer}")
    return lines


def export_static_objects(replay: Replay, layer: int = 1, header: Optional[str] = None) -> str:
    """Text of the recovered networked static objects (CRLF, like the retail file)."""
    objects = static_objects(replay)
    out: List[str] = [f"rem **** bf2demo parser: networked static objects of {replay.demo.header.map_name} ****",
                      f"rem {len(objects)} objects from the join snapshot; layer/light mask/overgrowth lines are not in a demo"]
    if header:
        out.append(f"rem {header}")
    moving = moving_statics(objects)
    if moving:
        out.append(f"rem {len(moving)} of them have physics: positions are exact only for a recording that starts at map load")
    out.append("")
    for obj in objects:
        out.extend(block(obj, layer))
        out.append("")
    return "\r\n".join(out)


def parse_static_blocks(text: str) -> List[Tuple[str, str, str]]:
    """``[(template, position, rotation)]`` of a retail ``StaticObjects.con`` (rotation ``""`` when absent); test/validation helper."""
    blocks: List[Tuple[str, str, str]] = []
    name = position = rotation = None
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if line.startswith("Object.create "):
            if name is not None:
                blocks.append((name, position or "", rotation or ""))
            name, position, rotation = line.split(None, 1)[1], None, None
        elif line.startswith("Object.absolutePosition "):
            position = line.split(None, 1)[1]
        elif line.startswith("Object.rotation "):
            rotation = line.split(None, 1)[1]
    if name is not None:
        blocks.append((name, position or "", rotation or ""))
    return blocks
