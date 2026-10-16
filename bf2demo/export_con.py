"""Reconstruct a level's ``GamePlayObjects.con`` from a recorded demo.

What a demo contains (and so what this exporter writes as *values*):

* **ControlPoint**: exact creation position, owner when the recording began, template name (template-id table).
* **ObjectSpawner**: spawners are server-only, but each vehicle they create is sent with its exact creation transform and team;
  a spawner is rebuilt from the vehicles it produced (:class:`bf2demo.replay.SpawnSite`). A static emplacement is in the join
  snapshot at its exact file position.
* **SpawnPoint**: every soldier spawn (``CreateKitEvent``) carries the exact spawn position; and every spawn group carries its
  centroid (:mod:`bf2demo.spawngroups`), which says whether a layout's points belong to this map even when nobody spawned.

Everything else (object names and order, the vehicle of a team that was never observed, spawn delays, control-point ids,
capture timers, ``CombatArea`` ...) is *static text*. It comes from the bundled retail layout of the level
(:mod:`bf2demo.layouts`) or from a file given with ``layout``, re-emitted character for character; only values the demo
observed are replaced.

Three rules make the result load and play like the recorded map:

1. **No new templates** (default). Template ids are a creation counter, and a client that has the original map files numbers
   its templates itself; one extra template shifts every later id and the client then decodes the object stream wrongly
   (``Networkable already added to network manager, netId=0``). Objects the layout lacks are therefore added as further
   *instances* of an existing template. ``allow_new_templates`` restores the old behaviour.
2. **Absent is not unobserved.** A layout spawner that the demo does not show is dropped only when that is provable: a vehicle
   for the owner of its control point, no delayed first spawn, a snapshot taken at map load (0 false drops over 22 retail maps). Everything
   else is kept and listed in the notes.
3. **Spawn points follow the groups.** A layout spawn group whose centroid is not among the demo's groups is not part of this
   map; its points are dropped (unless a soldier was seen spawning there).

Long lines hang the dedicated server while it loads the map, so the notes block is wrapped (:data:`export_blocks.MAX_LINE`).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from .export_blocks import (DEFAULT_AUTHOR, HEADER, MAX_LINE, NEW_SPAWN_OFFSET_Y, duplicate_instance, expand, fmt, insert_before_trailing_blank,  # noqa: F401
                            majority, new_cp_blocks, new_point_blocks, new_spawner_instance, new_spawner_template,
                            replace_prop, set_rotation, slots_of, vec, wrap_rem)
from .export_observe import (ABSENCE_MAX_TICK, LATE_RECORDING_TICK, MATCH_RADIUS, MATCH_XZ, DemoPoint, DemoSpawner,  # noqa: F401
                             ExportOptions, cp_team_at, observe)
from .layouts import Item, layout_text, parse_layout
from .replay import Replay
from .spawngroups import centroid_cell, cell_center, demo_groups, world_size

DEFAULT_SPAWN_OFFSET_Y = 1.02          # engine default when a template has no explicit offset

_SYNTHETIC = """rem ********** Object Spawner **********
if v_arg1 == host

endIf

rem ********** Spawn Points **********
rem ********** Control Points **********
if v_arg1 == host

endIf
"""


class _Exporter:
    def __init__(self, replay: Replay, opt: ExportOptions) -> None:
        self.replay, self.opt = replay, opt
        self.demo_cps, self.spawners, self.points = observe(replay, opt)
        self.first_tick = replay.object_history[0].created_tick if replay.object_history else 0
        self.source = "none (generic retail-style layout)"
        text = opt.layout
        if text is not None:
            self.source = "layout file given by the user"
        elif opt.use_layout:
            text = layout_text(replay.level, replay.game_mode, replay.map_size)
            if text is not None:
                self.source = (f"bundled retail layout {replay.level} {replay.game_mode}/{replay.map_size} "
                               f"(static text only)")
        self.allow_new = opt.allow_new_templates or text is None      # without a layout there is no template list to stay compatible with
        self.items = expand(parse_layout(text if text is not None else _SYNTHETIC))
        self.tpl_at: Dict[Tuple[str, str], int] = {(it.cls, it.name.lower()): idx for idx, it in enumerate(self.items)
                                                  if it.is_block and it.is_template}
        self.author = opt.author or majority([it.prop("modifiedByUser") for it in self.items
                                              if it.is_block and it.is_template], DEFAULT_AUTHOR)
        self.layer = majority([it.prop("layer") for it in self.items if it.is_block and not it.is_template],
                              str(opt.layer) if opt.layer is not None else "5")
        self.cp_match: Dict[int, str] = {}              # demo control point index -> layout control point name
        self.sp_match: Dict[int, int] = {}              # demo spawner index -> layout instance item index
        self.sp_same_place: Set[int] = set()            # matched by position: the very same object, so its control point id is right
        self.pt_match: Dict[int, int] = {}              # demo spawn point index -> layout instance item index
        self.dropped: Dict[str, List[str]] = {"spawner": [], "spawnpoint": []}
        self.skipped: List[str] = []                    # objects that would need a new template
        self.extra_spawners: List[Tuple[DemoSpawner, str, Dict[int, str]]] = []
        self.placeholders: List[str] = []
        self.foreign_groups: List[str] = []
        self.custom_groups: List[str] = []
        self.notes: List[str] = []

    # ------------------------------------------------------------------ layout queries
    def instances(self, cls: str) -> List[Tuple[int, str, Optional[tuple]]]:
        return [(idx, it.name, it.vec("absolutePosition")) for idx, it in enumerate(self.items)
                if it.is_block and not it.is_template and it.cls == cls]

    def template_of(self, cls: str, name: str) -> Optional[Item]:
        idx = self.tpl_at.get((cls, name.lower()))
        return self.items[idx] if idx is not None else None

    def layout_cp_id(self, cp_state) -> Optional[str]:
        for i, dc in enumerate(self.demo_cps):
            if dc.state is cp_state and i in self.cp_match:
                return self.template_of("controlpoint", self.cp_match[i]).prop("controlPointId")
        return None

    # ------------------------------------------------------------------ matching
    def match_control_points(self) -> None:
        layout = [(n, p) for _, n, p in self.instances("controlpoint")]
        for i, dc in enumerate(self.demo_cps):
            hit = next((n for n, _ in layout if n.lower() == dc.name.lower()), None)
            if hit is None:
                free = [(math.dist(p, dc.position), n) for n, p in layout if n not in self.cp_match.values() and p]
                if free and min(free)[0] <= MATCH_RADIUS:
                    hit = min(free)[1]
            if hit:
                self.cp_match[i] = hit

    def _spawner_instances(self):
        out = []
        for idx, name, pos in self.instances("objectspawner"):
            tpl = self.template_of("objectspawner", name)
            if tpl is not None and pos:
                out.append((idx, name, pos, slots_of(tpl), self.items[idx].prop("setControlPointId")))
        return out

    @staticmethod
    def _fits(ds: DemoSpawner, slots: Dict[int, str]) -> bool:
        """The layout spawner offers the vehicles the demo saw: in the team slot when the object's own team says which,
        otherwise in any slot (the control point of a spawner is not on the wire and its nearest flag is no proof)."""
        reliable = ds.reliable_slots
        if not all(slots.get(k, "").lower() == v.lower() for k, v in reliable.items()):
            return False
        offered = {v.lower() for v in slots.values()}
        return all(v.lower() in offered for v in ds.vehicles if v not in reliable.values())

    def cp_id_for_new_spawner(self, ds: DemoSpawner) -> Optional[str]:
        """Layout control point id for a spawner the layout does not place: the nearest flag whose owner fits the team of the
        vehicle when the object says which team it is, else simply the nearest flag (geometry is only a hint on a custom map)."""
        slots = ds.reliable_slots
        candidates = [(dc, name) for i, name in self.cp_match.items() for dc in [self.demo_cps[i]]
                      if not slots or dc.team in slots]
        if not candidates:
            return self.layout_cp_id(ds.cp)
        dc, name = min(candidates, key=lambda c: math.dist(c[0].position, ds.position))
        return self.template_of("controlpoint", name).prop("controlPointId")

    def resolved_slots(self, i: int) -> Tuple[Dict[int, str], List[str]]:
        """``(team slots, vehicles whose slot stays unknown)`` of a spawner matched to a layout instance.

        The object's own team (1 or 2) names the slot. A neutral object (team 0: static weapons) needs the control point, which is
        not on the wire: when the instance was matched by position it is the very same object, so its ``setControlPointId`` and
        that flag's owner decide, but only for a vehicle the template does not offer (a changed type). A neutral vehicle the
        template already offers needs no slot, and a moved spawner's retail control point id says nothing about the custom map.
        """
        ds = self.spawners[i]
        owner_of = None
        if i in self.sp_same_place:
            cp_id = self.items[self.sp_match[i]].prop("setControlPointId")
            for j, name in self.cp_match.items():
                if cp_id is not None and self.template_of("controlpoint", name).prop("controlPointId") == cp_id:
                    owner_of = self.demo_cps[j].state
        template = self.template_of("objectspawner", self.items[self.sp_match[i]].name)
        offered = {v.lower() for v in slots_of(template).values()} if template is not None else set()
        slots: Dict[int, str] = {}
        unknown: List[str] = []
        for tick, vehicle, team in ds.observations:
            slot = team if team in (1, 2) else None
            if slot is None and owner_of is not None and vehicle.lower() not in offered:
                owner = cp_team_at(owner_of, tick)
                slot = owner if owner in (1, 2) else None
            if slot is None:
                if vehicle not in unknown:
                    unknown.append(vehicle)
            else:
                slots.setdefault(slot, vehicle)
        return slots, unknown

    def match_spawners(self) -> None:
        """Demo sites -> layout spawner instances, strongest evidence first.

        1. same place (within :data:`MATCH_RADIUS`) and the template offers the vehicle(s): the very same object;
        2. the template offers the vehicle(s), anywhere (a moved or re-created spawner; same control point preferred);
        3. same place but another vehicle: a spawner whose vehicle type was changed.
        Positions of a custom map can be shuffled among the spawners, so "same place" alone proves nothing.
        """
        layout = self._spawner_instances()
        taken: Set[int] = set()
        near = sorted((math.dist(s.position, p), i, idx) for i, s in enumerate(self.spawners) for idx, _, p, _, _ in layout)
        slots_at = {idx: slots for idx, _, _, slots, _ in layout}

        def assign(i: int, idx: int, same_place: bool) -> None:
            self.sp_match[i] = idx
            taken.add(idx)
            if same_place:
                self.sp_same_place.add(i)

        for d, i, idx in near:                                          # 1
            if d > MATCH_RADIUS:
                break
            if i not in self.sp_match and idx not in taken and self._fits(self.spawners[i], slots_at[idx]):
                assign(i, idx, True)
        for i, s in sorted(enumerate(self.spawners), key=lambda p: p[1].site.first_tick):    # 2
            if i in self.sp_match or not s.vehicles:
                continue
            want_cp = self.cp_id_for_new_spawner(s)
            best = None
            for idx, _, p, slots, cpid in layout:
                if idx in taken or not self._fits(s, slots):
                    continue
                score = (cpid == want_cp and want_cp is not None, -math.dist(s.position, p))
                if best is None or score > best[0]:
                    best = (score, idx)
            if best:
                assign(i, best[1], False)
        for d, i, idx in near:                                          # 3
            if d > MATCH_RADIUS:
                break
            if i not in self.sp_match and idx not in taken:
                assign(i, idx, True)

    def match_points(self) -> None:
        layout = [(idx, p) for idx, _, p in self.instances("spawnpoint") if p]
        pairs = sorted((math.hypot(dp.position[0] - p[0], dp.position[2] - p[2]), i, idx)
                       for i, dp in enumerate(self.points) for idx, p in layout)
        taken: Set[int] = set()
        for d, i, idx in pairs:
            if d > MATCH_XZ:
                break
            if i not in self.pt_match and idx not in taken:
                self.pt_match[i] = idx
                taken.add(idx)

    # ------------------------------------------------------------------ what is provably absent / foreign
    def _is_known_vehicle(self, name: str) -> bool:
        info = self.replay.templates.info_by_name(name) if self.replay.templates else None
        return bool(info and info.cls.lower() == "playercontrolobject")

    def _not_yet_spawned(self, template: Item) -> bool:
        """The spawner delays its first vehicle (``spawnDelayAtStart``) for longer than the recording had run."""
        start = template.prop("spawnDelayAtStart")
        if not start or float(start) == 0:
            return False
        longest = template.prop("maxSpawnDelay") or template.prop("minSpawnDelay")
        return longest is None or float(longest) * 30 > self.first_tick      # no value: the engine default is unknown

    def provably_absent(self, idx: int) -> bool:
        """A spawner whose vehicle for the owner of its control point is not in a map-load snapshot.

        Every demo site was matched to a layout spawner by vehicle (anywhere on the map), so a vehicle that was displaced by
        physics is accounted for. Not provable when the spawner delays its first vehicle: the Taraba artillery
        (``minSpawnDelay 2400``, ``spawnDelayAtStart 1``) is created after forty minutes and is in no early snapshot although
        the map has it. 0 false drops over the 22 retail maps.
        """
        if not self.opt.drop_absent_spawners or self.first_tick > ABSENCE_MAX_TICK:
            return False
        item = self.items[idx]
        template = self.template_of("objectspawner", item.name)
        cp_id = item.prop("setControlPointId")
        if template is None or cp_id is None or self._not_yet_spawned(template):
            return False
        for i, name in self.cp_match.items():
            if self.template_of("controlpoint", name).prop("controlPointId") == cp_id:
                owner = self.demo_cps[i].team
                vehicle = slots_of(template).get(owner) if owner in (1, 2) else None
                return bool(vehicle) and self._is_known_vehicle(vehicle)
        return False

    def analyse_spawn_groups(self) -> Tuple[Set[int], List]:
        """``(layout spawn point instances that are foreign to this map, demo groups without a layout group)``."""
        size = world_size(self.replay.level)
        groups = demo_groups(self.replay)
        if not size or not groups:
            return set(), []
        layout_groups: Dict[tuple, List[int]] = {}
        for idx, name, pos in self.instances("spawnpoint"):
            tpl = self.template_of("spawnpoint", name)
            if tpl is not None and pos:
                layout_groups.setdefault((tpl.prop("setControlPointId"), tpl.prop("setGroup")), []).append(idx)
        demo_cells = {g.cell for g in groups}
        foreign: Set[int] = set()
        matched_cells: Set[tuple] = set()
        for key, idxs in layout_groups.items():
            cell = centroid_cell([self.items[i].vec("absolutePosition") for i in idxs], size)
            if cell in demo_cells:
                matched_cells.add(cell)
            else:
                foreign.update(idxs)
                self.foreign_groups.append(f"control point {key[0]} group {key[1] or 0} ({len(idxs)} points)")
        return foreign, [g for g in groups if g.cell not in matched_cells]

    # ------------------------------------------------------------------ export
    def run(self) -> str:
        opt, replay = self.opt, self.replay
        self.match_control_points()
        self.match_spawners()
        self.match_points()
        foreign, custom_groups = self.analyse_spawn_groups()
        cp_instance = {name: idx for idx, name, _ in self.instances("controlpoint")}
        matched = {"objectspawner": set(self.sp_match.values()), "spawnpoint": set(self.pt_match.values()),
                   "controlpoint": {cp_instance[n] for n in self.cp_match.values()}}
        by_idx_sp = {idx: self.spawners[i] for i, idx in self.sp_match.items()}
        self.match_slots = {idx: self.resolved_slots(i) for i, idx in self.sp_match.items()}
        by_tpl_sp: Dict[str, Tuple[DemoSpawner, Dict[int, str]]] = {}
        for idx, ds in by_idx_sp.items():
            by_tpl_sp.setdefault(self.items[idx].name.lower(), (ds, self.match_slots[idx][0]))
        by_idx_pt = {idx: self.points[i] for i, idx in self.pt_match.items()}
        by_name_cp = {n.lower(): self.demo_cps[i] for i, n in self.cp_match.items()}
        used_templates = {cls: {self.items[i].name.lower() for i in idxs} for cls, idxs in matched.items()}
        drop_unobserved = not opt.keep_unobserved

        self.out = []
        self.omitted: Counter = Counter()
        self.kept_unobserved: Counter = Counter()
        self.kept_slots: List[str] = []
        for idx, it in enumerate(self.items):
            if not it.is_block:
                line = it.lines[0]
                if HEADER.match(line):
                    line = line[:-11] + " (bf2demo parser) **********"
                self.out.append(Item([line]))
                continue
            if it.is_template:
                if it.name.lower() not in used_templates[it.cls]:
                    if drop_unobserved and self.allow_new:      # legacy: dropping a template renumbers every later one
                        self.omitted[it.cls] += 1
                        continue
                    self.kept_unobserved[it.cls] += 1
                self.out.append(self._rewrite_template(it, by_tpl_sp, by_name_cp))
                continue
            if idx in matched[it.cls]:
                self.out.append(self._rewrite_instance(idx, it, by_idx_sp, by_idx_pt, by_name_cp))
            elif it.cls == "objectspawner" and self.provably_absent(idx):
                self.dropped["spawner"].append(it.name)
            elif it.cls == "spawnpoint" and idx in foreign:
                self.dropped["spawnpoint"].append(it.name)
            elif not drop_unobserved:
                self.out.append(it)
        self.foreign_idx = foreign
        self._add_missing(custom_groups)
        lines = [line for it in self.out for line in it.lines]
        wrapped = [piece for note in self._notes(replay) for piece in wrap_rem(note)]
        return "\n".join(lines + [""] + wrapped) + "\n"

    # ------------------------------------------------------------------ rewriting matched blocks
    def _rewrite_template(self, it: Item, by_tpl_sp, by_name_cp) -> Item:
        lines = list(it.lines)
        key = it.name.lower()
        if it.cls == "objectspawner" and key in by_tpl_sp:
            ds, observed = by_tpl_sp[key]
            have = slots_of(it)
            last = max((i for i, l in enumerate(lines)
                        if re.match(r"^\s*ObjectTemplate\.setObjectTemplate\s", l, re.I)), default=None)
            for slot, tpl in sorted(observed.items()):
                new = f"ObjectTemplate.setObjectTemplate {slot} {tpl}"
                if slot in have:
                    if have[slot].lower() != tpl.lower():
                        for i, l in enumerate(lines):
                            if re.match(rf"^\s*ObjectTemplate\.setObjectTemplate\s+{slot}\s", l, re.I):
                                lines[i] = new
                else:
                    if last is None:
                        last = next((i for i, l in enumerate(lines) if "hasMobilePhysics" in l), len(lines) - 2)
                    lines.insert(last + 1, new)
                    last += 1
            if ds.team_on_vehicle and not any("teamOnVehicle" in l for l in lines):
                insert_before_trailing_blank(lines, "ObjectTemplate.teamOnVehicle 1")
            for slot in sorted(set(have) - set(observed)):
                self.kept_slots.append(f"{it.name} slot {slot} = {have[slot]}")
        elif it.cls == "controlpoint" and key in by_name_cp:
            dc = by_name_cp[key]
            has_team = any(re.match(r"^\s*ObjectTemplate\.team\s", l, re.I) for l in lines)
            if dc.team and has_team:
                replace_prop(lines, "team", str(dc.team))
            elif dc.team:
                at = next((i for i, l in enumerate(lines) if re.match(r"^\s*ObjectTemplate\.radius\s", l, re.I)), len(lines) - 2)
                lines.insert(at + 1, f"ObjectTemplate.team {dc.team}")
            elif has_team:
                lines = [l for l in lines if not re.match(r"^\s*ObjectTemplate\.team\s", l, re.I)]
        return Item(lines, it.cls, True, it.name)

    def _rewrite_instance(self, idx, it: Item, by_idx_sp, by_idx_pt, by_name_cp) -> Item:
        lines = list(it.lines)
        if it.cls == "objectspawner":
            ds = by_idx_sp[idx]
            replace_prop(lines, "absolutePosition", vec(ds.position))
            set_rotation(lines, ds.rotation)
            cp_id = self._control_point_for_moved_spawner(idx)
            if cp_id is not None:
                replace_prop(lines, "setControlPointId", cp_id)
        elif it.cls == "spawnpoint":
            dp = by_idx_pt[idx]
            tpl = self.template_of("spawnpoint", it.name)
            off = tpl.prop("setSpawnPositionOffset") if tpl else None
            off_y = float(off.split("/")[1]) if off else DEFAULT_SPAWN_OFFSET_Y
            replace_prop(lines, "absolutePosition", vec((dp.position[0], dp.position[1] - off_y, dp.position[2])))
        else:
            replace_prop(lines, "absolutePosition", vec(by_name_cp[it.name.lower()].position))
        return Item(lines, it.cls, False, it.name)

    def _control_point_for_moved_spawner(self, idx: int) -> Optional[str]:
        """A spawner matched by vehicle (not by place) must belong to a flag whose owner makes the observed vehicle spawn.

        The vehicle exists at the start of the recording, so the control point of the instance has to be owned by the team of
        the slot that offers it. The retail id is kept when it already fits; otherwise the nearest flag that fits is used.
        The real id is not on the wire (54 of 73 spawners of the customised Taraba are bound to a flag that is not the nearest).
        """
        i = next(i for i, j in self.sp_match.items() if j == idx)
        if i in self.sp_same_place:
            return None
        ds = self.spawners[i]
        item = self.items[idx]
        slots = slots_of(self.template_of("objectspawner", item.name))
        teams = set(ds.reliable_slots) or {k for k, v in slots.items() if v.lower() in {x.lower() for x in ds.vehicles}}
        if not teams:
            return None
        current = item.prop("setControlPointId")
        fitting = [(dc, name) for j, name in self.cp_match.items() for dc in [self.demo_cps[j]] if dc.team in teams]
        if not fitting:
            return None
        if any(self.template_of("controlpoint", name).prop("controlPointId") == current for _, name in fitting):
            return None
        dc, name = min(fitting, key=lambda c: math.dist(c[0].position, ds.position))
        return self.template_of("controlpoint", name).prop("controlPointId")

    # ------------------------------------------------------------------ objects the layout does not have
    def _anchor(self, cls: str, is_template: bool) -> int:
        out = self.out
        last = max((i for i, it in enumerate(out) if it.is_block and it.cls == cls and it.is_template == is_template),
                   default=None)
        if last is not None:
            return last + 1
        if not is_template:
            # every instance of the class was dropped: a new one must still come after the templates it is created from
            tpl_last = max((i for i, it in enumerate(out) if it.is_block and it.cls == cls and it.is_template), default=None)
            if tpl_last is not None:
                return tpl_last + 1
        hdr = {"objectspawner": "Object Spawner", "spawnpoint": "Spawn Points", "controlpoint": "Control Points"}[cls]
        h = next((i for i, it in enumerate(out) if not it.is_block and it.lines[0].startswith("rem *") and hdr in it.lines[0]), 0)
        if is_template or cls == "spawnpoint":
            return h + 1
        iff = next((i for i in range(h, len(out)) if not out[i].is_block and out[i].lines[0].startswith("if v_arg1")), h)
        return iff + 2 if iff + 1 < len(out) and out[iff + 1].lines[0] == "" else iff + 1

    def _add_missing(self, custom_groups) -> None:
        opt = self.opt
        additions: List[Tuple[int, List[Item]]] = []
        used = {it.name.lower() for it in self.items if it.is_block}
        ids = [int(float(v)) for v in (it.prop("controlPointId") for it in self.items
                                       if it.is_block and it.is_template and it.cls == "controlpoint") if v]
        next_id = max(ids + [0]) + 1
        explicit = opt.cp_ids or []
        new_cp_ids: Dict[int, int] = {}

        def free_name(stem):
            n, k = stem, 0
            while n.lower() in used:
                k += 1
                n = f"{stem}_{k}"
            used.add(n.lower())
            return n

        for i, dc in enumerate(self.demo_cps):                      # control points the layout lacks: a new template is unavoidable
            if i in self.cp_match:
                continue
            if not self.allow_new:
                self.skipped.append(f"control point {dc.name} (needs a new template)")
                continue
            cid = explicit[i] if i < len(explicit) else next_id
            next_id = max(next_id, int(cid)) + 1
            new_cp_ids[id(dc.state)] = cid
            t, n = new_cp_blocks(dc, self.author, cid, self.layer)
            additions.append((self._anchor("controlpoint", True), [Item(t, "controlpoint", True, dc.name)]))
            additions.append((self._anchor("controlpoint", False), [Item(n, "controlpoint", False, dc.name)]))
            used.add(dc.name.lower())

        def cp_id_for(cp_state):
            got = self.layout_cp_id(cp_state)
            if got is not None:
                return got
            return new_cp_ids.get(id(cp_state), 0) if cp_state is not None else 0

        late_moved: List[str] = []
        layout_sp = self._spawner_instances()
        for i, ds in enumerate(self.spawners):
            if i in self.sp_match:
                continue
            if not ds.site.exact and self.first_tick > LATE_RECORDING_TICK:
                late_moved.append(ds.site.observations[0][1])      # most likely driven away from its spawner
                continue
            label = ", ".join(ds.vehicles)
            source = self._template_for_new_spawner(ds, layout_sp)
            if source is not None:                                  # another object of an existing template
                additions.append((self._anchor("objectspawner", False),
                                  [duplicate_instance(self.items[source], ds.position, ds.rotation,
                                                      self.cp_id_for_new_spawner(ds))]))
                slots = next(sl for idx, _, _, sl, _ in layout_sp if idx == source)
                self.extra_spawners.append((ds, self.items[source].name,
                                            {k: v for k, v in slots.items() if k not in ds.slots}))
            elif self.allow_new:
                name = free_name(f"{ds.cp.template.name if ds.cp else 'Level'}_{ds.site.observations[0][1]}")
                additions.append((self._anchor("objectspawner", True),
                                  [Item(new_spawner_template(name, ds, self.author), "objectspawner", True, name)]))
                additions.append((self._anchor("objectspawner", False),
                                  [Item(new_spawner_instance(name, ds, cp_id_for(ds.cp), self.layer), "objectspawner", False, name)]))
            else:
                self.skipped.append(f"spawner for {label} at {vec(ds.position)} (no layout spawner offers it)")
        self.late_moved = late_moved
        self._add_points(additions, custom_groups, free_name, cp_id_for)
        for index, (pos, new_items) in sorted(enumerate(additions), key=lambda p: (-p[1][0], -p[0])):
            self.out[pos:pos] = new_items       # from the back so earlier anchors stay valid; same anchor keeps discovery order

    def _template_for_new_spawner(self, ds: DemoSpawner, layout_sp) -> Optional[int]:
        """An existing instance whose template can produce this site's vehicle(s): same control point and nearest first."""
        want_cp = self.cp_id_for_new_spawner(ds)
        best = None
        for idx, name, pos, slots, cpid in layout_sp:
            if not self._fits(ds, slots):
                continue
            exact = bool(ds.slots) and set(slots) == set(ds.slots)       # no vehicle for a team that was not observed
            score = (exact, cpid == want_cp and want_cp is not None, -math.dist(ds.position, pos))
            if best is None or score > best[0]:
                best = (score, idx)
        return best[1] if best else None

    def _spawn_template_source(self, cp_id: Optional[str], preferred: Set[int], avoid_keys: Set[tuple] = frozenset()) -> Optional[int]:
        """An existing spawn point instance of the control point to copy.

        Preferred: one of a group that is not used yet (``avoid_keys`` holds the ``(control point, group)`` pairs already taken, so
        every announced spawn group gets its own engine group) and one the export dropped as foreign.
        """
        candidates = []
        for idx, name, _ in self.instances("spawnpoint"):
            tpl = self.template_of("spawnpoint", name)
            if tpl is not None and tpl.prop("setControlPointId") == cp_id:
                key = (cp_id, tpl.prop("setGroup"))
                candidates.append((key not in avoid_keys, idx in preferred, idx))
        return max(candidates)[2] if candidates else None

    def _group_key(self, idx: int) -> tuple:
        tpl = self.template_of("spawnpoint", self.items[idx].name)
        return (tpl.prop("setControlPointId"), tpl.prop("setGroup")) if tpl else (None, None)

    def _add_points(self, additions, custom_groups, free_name, cp_id_for) -> None:
        opt = self.opt
        foreign_idx = self.foreign_idx
        counters: Counter = Counter()
        for i, dp in enumerate(self.points):
            if i in self.pt_match:
                continue
            cid = cp_id_for(dp.cp)
            source = self._spawn_template_source(cid, foreign_idx)
            if source is not None:
                src = self.items[source]
                tpl = self.template_of("spawnpoint", src.name)
                off = tpl.prop("setSpawnPositionOffset") if tpl else None
                off_y = float(off.split("/")[1]) if off else DEFAULT_SPAWN_OFFSET_Y
                additions.append((self._anchor("spawnpoint", False), [duplicate_instance(
                    src, (dp.position[0], dp.position[1] - off_y, dp.position[2]))]))
            elif self.allow_new:
                stem = dp.cp.template.name if dp.cp else "Level"
                counters[stem] += 1
                name = free_name(f"{stem}_{counters[stem]}")
                t, n = new_point_blocks(name, dp.position, self.author, cid, self.layer)
                additions.append((self._anchor("spawnpoint", False), [Item(t, "spawnpoint", True, name), Item(n, "spawnpoint", False, name)]))
            else:
                self.skipped.append(f"spawn point at {vec(dp.position)} (control point {cid} has no spawn point template)")
        size = world_size(self.replay.level)
        used_keys: Set[tuple] = set()
        for group in custom_groups:
            cx, cz = group.center(size)
            near = [dp for dp in self.points if math.hypot(dp.position[0] - cx, dp.position[2] - cz) <= size / 255.0]
            self.custom_groups.append(f"group {group.group_id} team {group.team} centroid x {cx:.0f} z {cz:.0f}"
                                      + (f" ({len(near)} observed spawns)" if near else " (no soldier spawned there)"))
            if not opt.placeholder_spawns or near or not self.demo_cps:
                continue
            cp = min(self.demo_cps, key=lambda c: math.hypot(c.position[0] - cx, c.position[2] - cz))
            cid = self.layout_cp_id(cp.state)
            source = self._spawn_template_source(cid, foreign_idx, used_keys)
            if source is not None:
                used_keys.add(self._group_key(source))
            if source is None:
                self.skipped.append(f"placeholder spawn point of group {group.group_id} (no spawn point template for its control point)")
                continue
            src = self.items[source]
            tpl = self.template_of("spawnpoint", src.name)
            off = tpl.prop("setSpawnPositionOffset") if tpl else None
            off_y = float(off.split("/")[1]) if off else DEFAULT_SPAWN_OFFSET_Y
            additions.append((self._anchor("spawnpoint", False), [duplicate_instance(src, (cx, cp.position[1], cz))]))
            self.placeholders.append(f"group {group.group_id} at x {cx:.1f} z {cz:.1f} y {cp.position[1]:.1f}")

    # ------------------------------------------------------------------ notes
    def _notes(self, replay: Replay) -> List[str]:
        spawners = self.spawners
        notes = ["rem ********** bf2demo parser notes **********",
                 f"rem demo: map {replay.demo.header.map_name}, mode {replay.game_mode}/{replay.map_size}, "
                 f"recorded {replay.demo.header.recorded_at}"
                 + (f", merged with {len(replay.merged_from) - 1} more recording(s) of {', '.join(replay.merged_from[1:])}"
                    if replay.merged_from else ""),
                 f"rem static text source: {self.source}",
                 f"rem recording started at tick {self.first_tick} (about 30 when recorded from map load); "
                 "ObjectTemplate.team of a control point is its owner at that moment",
                 "rem observed in the demo: positions, rotations, control point owners, vehicle per team slot, "
                 "soldier spawns, spawn group centroids",
                 "rem copied from the static text, NOT observed: names/order, other-team vehicle slots, "
                 "spawn delays,",
                 "rem   controlPointId, capture radius/timers, SpawnPoint rotation, CombatArea"]
        if not self.allow_new:
            notes.append("rem no object template was added: the template list is the layout's, so clients with the original "
                         "map files stay in sync")
        for kind, label in (("objectspawner", "spawners"), ("spawnpoint", "spawn points"), ("controlpoint", "control points")):
            if self.omitted[kind]:
                notes.append(f"rem {self.omitted[kind]} {label} of the layout were not seen in this demo and are omitted")
            if self.kept_unobserved[kind]:
                notes.append(f"rem {self.kept_unobserved[kind]} {label} were not seen in this demo: kept exactly as in the "
                             f"layout (their numbers are NOT from the demo)")
        if self.dropped["spawner"]:
            notes.append(f"rem {len(self.dropped['spawner'])} spawners of the layout are missing from the map-load "
                         "snapshot although their control point owner has a vehicle there: the map does not have them: "
                         + ", ".join(self.dropped["spawner"]))
        if self.dropped["spawnpoint"]:
            notes.append(f"rem {len(self.dropped['spawnpoint'])} spawn points were dropped: their spawn group centroid is not "
                         "among the groups of the demo, so they are not part of this map: " + "; ".join(self.foreign_groups))
        if self.custom_groups:
            notes.append(f"rem {len(self.custom_groups)} spawn groups of the demo have no layout counterpart (only their centroid "
                         "is known; soldiers spawning there would reveal the points): " + "; ".join(self.custom_groups))
        if self.placeholders:
            notes.append("rem PLACEHOLDER spawn points (one per such group, Y = the flag's): " + "; ".join(self.placeholders))
        if self.extra_spawners:
            notes.append(f"rem {len(self.extra_spawners)} spawners are further instances of existing spawner templates: "
                         + ", ".join(f"{', '.join(ds.vehicles)} as {name}"
                                     + (f" (the template also gives team {', '.join(f'{k}: {v}' for k, v in sorted(extra.items()))}"
                                        " whenever that team owns the point)" if extra else "")
                                     for ds, name, extra in self.extra_spawners))
        if self.skipped:
            notes.append(f"rem {len(self.skipped)} objects were NOT exported because they would need a new template (use "
                         "allow_new_templates): " + "; ".join(self.skipped))
        estimated = [self.items[idx].name for i, idx in self.sp_match.items() if spawners[i].estimated_dy is not None]
        if estimated:
            notes.append(f"rem {len(estimated)} spawners: Y ESTIMATED (snapshot Y minus the learned rest height of the vehicle "
                         "template; exact when the spawner stands on terrain): " + ", ".join(estimated))
        approximate = [self.items[idx].name for i, idx in self.sp_match.items()
                       if spawners[i].note and not spawners[i].site.exact and spawners[i].estimated_dy is None]
        if approximate:
            notes.append(f"rem {len(approximate)} spawners are mobile vehicles seen only in the join snapshot (Y/rotation "
                         "approximate; a recording that includes their respawn gives exact values): " + ", ".join(approximate))
        for i, idx in self.sp_match.items():
            ds, label = spawners[i], self.items[idx].name
            if ds.note and ds.site.exact:
                notes.append(f"rem spawner {label}: {ds.note}")
            for template in self.match_slots[idx][1]:
                notes.append(f"rem spawner {label}: vehicle {template} seen, team slot not observable")
        if self.late_moved:
            notes.append(f"rem {len(self.late_moved)} mobile vehicles seen only in the snapshot of a mid-round recording match "
                         "no layout spawner (probably driven away before recording) and were not exported as new "
                         "spawners: " + ", ".join(self.late_moved))
        if self.kept_slots:
            notes.append(f"rem {len(self.kept_slots)} team slots of observed spawners were not observed and are kept "
                         "as in the layout: " + "; ".join(self.kept_slots))
        for i, dp in enumerate(self.points):
            idx = self.pt_match.get(i)
            notes.append(f"rem spawn point {self.items[idx].name if idx is not None else '(new)'}: soldier spawned here {dp.count}x")
        return notes


def export_gameplay_objects(replay: Replay, options: Optional[ExportOptions] = None) -> str:
    """Return the reconstructed file (LF line ends; write it as CRLF)."""
    return _Exporter(replay, options or ExportOptions()).run()
