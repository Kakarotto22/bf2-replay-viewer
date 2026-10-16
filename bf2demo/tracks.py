"""Object tracks: where every soldier, vehicle and supply object was, tick by tick.

Ghost bodies start with the object's pose: ``SoldierNetworkable`` (soldiers) or ``SimpleObjectNetworkable`` (vehicles,
supply objects, UAVs, parachutes). Positions are absolute float32 triples in every sample of every demo checked, so
no baseline tracking is needed. Soldiers are tied to their player through ``GameObject.owner_id``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .bitstream import BitStream
from .objectnet import (SimpleObjectContext, UnsupportedLayout, decode_child_pco, decode_generic_projectile, decode_simple_object,
                        decode_simple_object_pose, decode_soldier, decode_triggerable_target, decode_vehicle, engine_units,
                        rotational_bundle_units)
from .packet import GHOST_UPDATE, PacketError, parse_packet
from .replay import GameObject, Replay

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]

#: Template classes whose ghost body starts with a SimpleObjectNetworkable (projectiles have their own networkable).
SIMPLE_CLASSES = ("PlayerControlObject", "SupplyObject", "UAVVehicle", "Parachute", "Triggerable")


@dataclass
class Track:
    obj: GameObject
    samples: List[Tuple[int, Vec3, Optional[Quat]]] = field(default_factory=list)   # (tick, position, rotation)
    ragdoll_from: Optional[int] = None        # tick of the first ragdoll update (soldier died)
    #: vehicle element updates in physical units (only with ``build_tracks(parts=True)``):
    #: ``(tick, scope, element index, kind, {field: value})``; scope 0 = the vehicle root ghost, k + 1 = k-th nested
    #: PlayerControlObject (turret / gunner seat); kind R rotational bundle (degrees), E engine, O rotor, S spring, D destroyable
    parts: List[Tuple[int, int, int, str, Dict[str, object]]] = field(default_factory=list)
    #: ``(tick, value)`` of the vehicle's health field (``SimpleObjectNetworkable`` mask 0x10): ``armor.maxHitPoints + armor.wreckHitPoints``
    #: when new, falling to 0 while the wreck burns; at or below ``wreckHitPoints`` the vehicle is destroyed (see ``wrecked_tick``)
    health: List[Tuple[int, int]] = field(default_factory=list)
    #: ``(tick, weapon item index)`` of a soldier: the weapon in hand (``SoldierNetworkable``), changes only
    items: List[Tuple[int, int]] = field(default_factory=list)

    @property
    def owner_id(self) -> Optional[int]:
        return self.obj.owner_id

    @property
    def wrecked_tick(self) -> Optional[int]:
        """Tick of the explosion: the first health sample at or below ``armor.wreckHitPoints`` (the vehicle is a burning wreck from then on
        until the object is removed ~10 s later). ``None`` for vehicles without a wreck phase and for ones that never got there."""
        wreck = self.obj.template.armor_wreck
        if not wreck:
            return None
        for tick, value in self.health:
            if value <= wreck:
                return tick
        return None

    def distance(self) -> float:
        total = 0.0
        for (_, a, _), (_, b, _) in zip(self.samples, self.samples[1:]):
            total += ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
        return total


def _part_values(letter: str, update, info: Dict[str, object]) -> Optional[Dict[str, object]]:
    """Physical values of one decoded vehicle element update (``None`` when it carried nothing)."""
    if letter == "R":
        return rotational_bundle_units(update, 12, info) or None
    if letter == "E":
        return engine_units(update, info) or None
    if letter in ("O", "D") and update.fields:
        return {k: v for k, v in update.fields.items() if k not in ("position", "rotation") or letter == "O"} or None
    if letter == "W" and update.fields:             # soldier riding in a passenger seat
        return {k: v for k, v in update.fields.items() if k in ("position", "ragdoll_root", "yaw", "pitch")} or None
    if letter == "S" and update.present:
        return dict(update.fields)
    return None


def _yaw_quaternion(yaw_degrees: float) -> Quat:
    """Quaternion stored in a track for a soldier's ``yaw`` field (compass degrees, 0 = +z, clockwise).

    Tracks follow the engine's convention (the stored rotation is the inverse of the body orientation, see ``web.viewer_format.heading_degrees``),
    so the rotation about the vertical axis is the conjugate. ``yaw`` is the direction the soldier aims: for 227 kills with hand weapons on
    ``zatar_wetlands_20261012-2136_18h`` it differs from the bearing killer -> victim by 4.9 degrees (median), 184 of 227 within 25 degrees;
    the movement heading minus yaw is 1 degree on average over 18910 moving samples of ``zxc.bf2demo``.
    """
    half = math.radians(yaw_degrees) / 2
    return (0.0, -math.sin(half), 0.0, math.cos(half))


def build_tracks(replay: Replay, projectiles: bool = True, parts: bool = False,
                 projectile_filter: Optional[Callable[[str], bool]] = None) -> Dict[Tuple[int, int], Track]:
    """Tracks keyed by ``(object_id, created_tick)``; ids are reused after DestroyObject.

    ``projectile_filter(template_name)`` keeps only some projectile templates (with ``projectiles=True``), e.g. artillery shells.
    ``parts=True`` also decodes the networkable elements of vehicles (turrets, engines, rotors, control surfaces) into
    ``Track.parts``; it needs the full body of every vehicle ghost and is slower.
    """
    tracks: Dict[Tuple[int, int], Track] = {}
    last_pose: Dict[Tuple[int, int], List[object]] = {}

    for packet in replay.demo.packets:
        if not packet.data or packet.tick < 0:
            continue
        try:
            pkt = parse_packet(packet.data)
        except PacketError:
            continue
        for ghost in pkt.ghosts:
            if ghost.action != GHOST_UPDATE:
                continue
            obj = replay.object_at(ghost.ghost_id, packet.tick)
            if obj is None and parts:
                _child_parts(replay, tracks, packet, ghost)
                continue
            if obj is None or obj.template is None:
                continue
            cls = obj.template.cls
            if cls not in ("Soldier", "TriggerableTarget") and cls not in SIMPLE_CLASSES                     and not (projectiles and cls == "GenericProjectile"
                                                             and (projectile_filter is None or projectile_filter(obj.template.name))):
                continue
            key = (obj.object_id, obj.created_tick)
            track = tracks.get(key)
            if track is None:
                track = tracks[key] = Track(obj)
            pose = last_pose.setdefault(key, [None, None])
            bs = BitStream(packet.data, ghost.bit_start)
            if cls == "Soldier":
                upd = decode_soldier(bs)
                if "weapon_item_index" in upd.fields:
                    track.items.append((packet.tick, upd.fields["weapon_item_index"]))
                if upd.ragdoll:
                    if track.ragdoll_from is None:
                        track.ragdoll_from = packet.tick
                    pose[0] = upd.fields["ragdoll_root"]
                elif "position" in upd.fields:
                    pose[0] = upd.fields["position"]
                else:
                    continue
                if "yaw" in upd.fields:
                    pose[1] = _yaw_quaternion(upd.fields["yaw"])
            elif cls == "TriggerableTarget":                 # moving map parts (Special Forces elevators): position only
                upd = decode_triggerable_target(bs)
                if "position" not in upd.fields:
                    continue
                pose[0] = upd.fields["position"]
            elif cls == "GenericProjectile":
                upd = decode_generic_projectile(bs, obj.template.range_bits)
                if "position" in upd.fields:
                    pose[0] = upd.fields["position"]
                if "rotation" in upd.fields:
                    pose[1] = upd.fields["rotation"]
                if "position" not in upd.fields:
                    continue
            else:
                collected: list = []
                if parts and obj.template.netseq is not None:
                    try:
                        decode_vehicle(bs, obj.template, parts=collected)
                        upd = collected[0][1]
                    except UnsupportedLayout:
                        collected = []
                        upd = decode_simple_object_pose(BitStream(packet.data, ghost.bit_start), bool(obj.template.mobile))
                elif cls == "PlayerControlObject" and obj.template.armor_wreck:
                    upd = decode_simple_object(bs, SimpleObjectContext(bool(obj.template.mobile), obj.template.range_bits, True))
                else:
                    upd = decode_simple_object_pose(bs, bool(obj.template.mobile))
                if cls == "PlayerControlObject" and "range_value" in upd.fields:
                    track.health.append((packet.tick, upd.fields["range_value"]))
                for index, (letter, update, info) in enumerate(collected[1:]):
                    values = _part_values(letter, update, info)
                    if values:
                        track.parts.append((packet.tick, 0, index, letter, values))
                if "position" in upd.fields:
                    pose[0] = upd.fields["position"]
                if "rotation" in upd.fields:
                    pose[1] = upd.fields["rotation"]
                if "position" not in upd.fields and "rotation" not in upd.fields:
                    continue
            if pose[0] is not None:
                track.samples.append((packet.tick, pose[0], pose[1]))
    return tracks


def _child_parts(replay: Replay, tracks, packet, ghost) -> None:
    """Ghost ids after a vehicle root belong to its nested PlayerControlObjects (``root id + 1 + index``)."""
    owner = replay.nested_owner(ghost.ghost_id, packet.tick)
    if owner is None:
        return
    root, index = owner
    track = tracks.get((root.object_id, root.created_tick))
    if track is None:
        track = tracks[(root.object_id, root.created_tick)] = Track(root)
    collected: list = []
    try:
        decode_child_pco(BitStream(packet.data, ghost.bit_start), root.template, index, parts=collected)
    except UnsupportedLayout:
        return
    for element, (letter, update, info) in enumerate(collected[1:]):
        values = _part_values(letter, update, info)
        if values:
            track.parts.append((packet.tick, index + 1, element, letter, values))


def _owner_name(replay: Replay, track: Track) -> str:
    from .feed import PlayerNames           # local import: feed imports replay, not tracks
    owner = track.owner_id
    if owner is None:
        return ""
    return PlayerNames(replay).name(owner, track.obj.created_tick)


def format_tracks(replay: Replay, tracks: Dict[Tuple[int, int], Track], limit: int = 60) -> str:
    """One line per track, longest distance first."""
    names = {}
    from .feed import PlayerNames
    pn = PlayerNames(replay)
    rows = []
    for track in tracks.values():
        owner = track.owner_id
        who = pn.name(owner, track.obj.created_tick) if owner is not None else "-"
        first, last = track.samples[0], track.samples[-1]
        rows.append((track.distance(), f"  {track.obj.template.name:<22} #{track.obj.object_id:<5} {who:<22} "
                     f"ticks {first[0]:>6}-{last[0]:>6}  {len(track.samples):>5} samples  "
                     f"{track.distance():8.1f} m" + ("  died@%d" % track.ragdoll_from if track.ragdoll_from else "")))
    rows.sort(key=lambda r: -r[0])
    out = [r[1] for r in rows[:limit]]
    if len(rows) > limit:
        out.append(f"  ... {len(rows) - limit} more tracks")
    return chr(10).join(out)


def write_tracks_csv(replay: Replay, tracks: Dict[Tuple[int, int], Track], path: str) -> None:
    import csv
    from .feed import PlayerNames
    pn = PlayerNames(replay)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tick", "object_id", "created_tick", "template", "class", "owner_player_id", "owner_name",
                    "x", "y", "z", "qx", "qy", "qz", "qw"])
        for track in sorted(tracks.values(), key=lambda t: (t.obj.created_tick, t.obj.object_id)):
            obj = track.obj
            owner = track.owner_id
            who = pn.name(owner, obj.created_tick) if owner is not None else ""
            for tick, pos, rot in track.samples:
                w.writerow([tick, obj.object_id, obj.created_tick, obj.template.name, obj.template.cls,
                            "" if owner is None else owner, who, f"{pos[0]:.4f}", f"{pos[1]:.4f}", f"{pos[2]:.4f}"]
                           + (["", "", "", ""] if rot is None else [f"{c:.5f}" for c in rot]))


def write_parts_csv(replay: Replay, tracks: Dict[Tuple[int, int], Track], path: str) -> None:
    """Long-format CSV of ``Track.parts``: one row per decoded field."""
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tick", "object_id", "created_tick", "template", "scope", "element", "kind", "field", "value"])
        for track in sorted(tracks.values(), key=lambda t: (t.obj.created_tick, t.obj.object_id)):
            obj = track.obj
            for tick, scope, element, kind, values in track.parts:
                for name, value in values.items():
                    if isinstance(value, (tuple, list)):
                        value = " ".join(f"{v:.4f}" for v in value)
                    elif isinstance(value, float):
                        value = f"{value:.4f}"
                    w.writerow([tick, obj.object_id, obj.created_tick, obj.template.name,
                                "root" if scope == 0 else f"seat{scope}", element, kind, name, value])
