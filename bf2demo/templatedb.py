"""ObjectTemplate id -> (class, name) resolution.

Template ids on the wire are ``ObjectTemplate::getId()`` values assigned
sequentially in creation order (see ``scripts/build_templates.py`` for the
reverse-engineered order). ``assets/templates.json.gz`` holds:

* ``global`` (``booster_global`` for the booster pack levels, whose archive is merged into the sorted .con order): templates created before any level is loaded (identical on
  every map of the retail 1.5.3153 server; verified against kits, soldiers,
  weapons and vehicles seen in the demos),
* ``levels[<level>][<mode>/<size>]``: templates the level adds afterwards,
* ``xpack``: the same two tables for the Special Forces mod (``mods/xpack``), whose own object archive is mounted before the
  base mod's; selected by the level name.

Ids of templates created by the level ``Init.con`` (level-specific vehicles
and objects) are exact. The ``GamePlayObjects.con`` part is short by a small
per-level constant, so it is aligned on the control-point block actually
present in the demo (:meth:`TemplateDB.align_level`).
"""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_PATH = os.path.join(os.path.dirname(__file__), "assets", "templates.json.gz")

#: ``SoundObjectTemplate`` ids come from a separate counter starting here.
SOUND_ID_BASE = 0x1000000


@dataclass(frozen=True)
class TemplateInfo:
    template_id: int
    cls: str
    name: str
    source: str  # "global", "level", or "unknown"
    mobile: Optional[bool] = None   # ObjectTemplate.hasMobilePhysics
    armor_max: Optional[float] = None     # armor.maxHitPoints
    armor_wreck: Optional[float] = None   # armor.wreckHitPoints (None: not set in the template files)
    netseq: Optional[str] = None          # networkable sequence after the SimpleObject of a PlayerControlObject ghost
    engines: Optional[list] = None        # per Engine element of netseq: {"gears": n | None, "type": "c_ET..."}
    #: nested PlayerControlObject templates in ``getAllPlayerControlObjects`` order (pre-order); the object with id
    #: ``root id + 1 + index`` has its own ghost: [netseq, engines] each
    pco_children: Optional[list] = None

    @property
    def range_bits(self) -> int:
        """Width of the health field of SimpleObject/GenericProjectile bodies: ``width_for(max + wreck hit points)``.

        Templates without ``armor.*`` data have a zero range, i.e. a 0-bit field (verified for 25 projectile templates).
        """
        total = int(self.armor_max or 0) + int(self.armor_wreck or 0)
        bits = 0
        while (1 << bits) - 1 < total:
            bits += 1
        return bits

    @property
    def is_vehicle(self) -> bool:
        return self.cls.lower() == "playercontrolobject"


def _info(template_id: int, entry: tuple, source: str) -> TemplateInfo:
    mobile = bool(entry[2]) if len(entry) > 2 and entry[2] is not None else None
    armor_max = entry[3] if len(entry) > 3 else None
    armor_wreck = entry[4] if len(entry) > 4 else None
    netseq = entry[5] if len(entry) > 5 else None
    engines = entry[6] if len(entry) > 6 else None
    children = entry[7] if len(entry) > 7 else None
    return TemplateInfo(template_id, entry[0], entry[1], source, mobile, armor_max, armor_wreck, netseq, engines, children)


@lru_cache(maxsize=1)
def _load() -> dict:
    with gzip.open(_PATH, "rt", encoding="utf-8") as fh:
        return json.load(fh)


class TemplateDB:
    def __init__(self, level: Optional[str] = None, layer: Optional[str] = None) -> None:
        data = _load()
        self.level = (level or "").lower()
        xpack = data.get("xpack", {})
        if self.level in xpack.get("levels", {}):
            # Special Forces (mods/xpack): its own archive is mounted before the base mod's, so the global block differs
            self._global: List[tuple] = [tuple(t) for t in xpack["global"]]
            level_doc = xpack["levels"][self.level]
        else:
            booster = self.level in data.get("booster_levels", [])
            self._global = [tuple(t) for t in data["booster_global" if booster else "global"]]
            level_doc = data["levels"].get(self.level, {})
        #: templates created by the level Init.con (ids not affected by the gap)
        self.init_count: int = level_doc.get("_init_count", 0)
        self.layers: Dict[str, List[Tuple[str, str]]] = {
            k: [tuple(t) for t in v] for k, v in level_doc.items() if not k.startswith("_")}
        self.layer = layer if layer in self.layers else None
        self.level_offset = 0
        self.aligned = False
        self._by_name: Optional[Dict[str, tuple]] = None

    @property
    def global_count(self) -> int:
        return len(self._global)

    @property
    def level_templates(self) -> List[Tuple[str, str]]:
        return self.layers.get(self.layer or "", [])

    def info_by_name(self, name: str) -> Optional[TemplateInfo]:
        """A template of the global table or of the selected level layer by (case-insensitive) name; its id is -1."""
        if self._by_name is None:
            table = {}
            for entry in list(self._global) + [tuple(t) for t in self.level_templates]:
                table.setdefault(entry[1].lower(), entry)
            self._by_name = table
        entry = self._by_name.get(name.lower())
        return _info(-1, entry, "global") if entry is not None else None

    def lookup(self, template_id: int) -> TemplateInfo:
        if template_id < self.global_count:
            return _info(template_id, self._global[template_id], "global")
        idx = template_id - self.global_count
        if idx >= self.init_count:
            if not self.aligned:
                return TemplateInfo(template_id, "Unknown", f"template_{template_id}", "unknown")
            idx -= self.level_offset
        level = self.level_templates
        if 0 <= idx < len(level):
            return _info(template_id, level[idx], "level")
        return TemplateInfo(template_id, "Unknown", f"template_{template_id}", "unknown")

    def predicted_control_points(self) -> List[Tuple[int, str]]:
        """``(index_in_level_layer, name)`` of the layer's ControlPoint templates."""
        return [(i, t[1]) for i, t in enumerate(self.level_templates) if t[0].lower() == "controlpoint"]

    def align_level(self, observed_cp_template_ids: Sequence[int]) -> bool:
        """Align the level layer so its ControlPoint block matches the demo.

        ``observed_cp_template_ids`` are the template ids of objects proven to
        be control points (their ghost updates decode exactly as
        ``ControlPointNetworkable``). Returns True when every observed id
        lands on a ControlPoint template of the selected layer.
        """
        predicted = self.predicted_control_points()
        observed = sorted(set(observed_cp_template_ids))
        if not predicted or not observed or len(observed) != len(predicted):
            return False
        offset = observed[0] - self.global_count - predicted[0][0]
        cp_indices = {i for i, _ in predicted}
        if all((t - self.global_count - offset) in cp_indices for t in observed):
            self.level_offset = offset
            self.aligned = True
        return self.aligned

    def select_layer(self, observed_cp_template_ids: Sequence[int],
                     mode: Optional[str] = None, size: Optional[int] = None) -> Optional[str]:
        """Pick the mode/size layer whose control-point block matches the demo.

        The layer announced by the server (``mode``/``size``) is tried first;
        otherwise any layer of the same mode, then any layer at all, whose
        control-point count and spacing match the observed block.
        """
        order: List[str] = []
        if mode and size:
            order.append(f"{mode}/{size}")
        order += sorted(k for k in self.layers if mode and k.startswith(f"{mode}/"))
        order += sorted(self.layers)
        for key in dict.fromkeys(order):
            if key not in self.layers:
                continue
            self.layer = key
            self.aligned = False
            self.level_offset = 0
            if self.align_level(observed_cp_template_ids):
                return key
        self.layer = order[0] if order and order[0] in self.layers else None
        return None
