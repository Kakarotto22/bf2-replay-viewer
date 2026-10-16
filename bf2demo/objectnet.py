"""Object networkables: ``SimpleObjectNetworkable`` and friends (ghost bodies of world objects).

A ghost update body is the concatenation of the networkable updates of the object, each starting
with its own change mask. Decoders here report the bits they consumed so a candidate sequence can be
checked against ``GhostRecord.bit_length`` (exact consumption is the evidence).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .bitstream import BitStream
from .ghostbits import (read_compressed_vector, read_high_compressed_vector, read_compressed_vector2, read_unit_quaternion, width_for,
                        _raw_vec as _raw_floats)


@dataclass
class SimpleObjectContext:
    """Per-object facts the decoder needs (they decide which optional fields exist).

    ``has_physics``: the object's physics component answers true at vtable +0x134 (``hasMobilePhysics``; raw call offset, add 8 for the slot in a vtable dump).
    ``range_bits``: bit width of the mask-0x10 field (component at object+0x3c; depends on the template).
    ``is_player_control``: object is (a child of) a PlayerControlObject; ``is_parachute`` selects the parachute field.
    """

    has_physics: bool = True
    range_bits: Optional[int] = None
    is_player_control: bool = False
    is_parachute: bool = False


@dataclass
class SimpleObjectUpdate:
    """``SimpleObjectNetworkable::setNetUpdate`` @ 0x08243990 (no baseline path)."""

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


class UnsupportedLayout(Exception):
    """The record needs information (e.g. the mask-0x10 width) that is not known for this object."""


def decode_simple_object(bs: BitStream, ctx: SimpleObjectContext) -> SimpleObjectUpdate:
    start = bs.bit_pos
    mask = bs.read_bits(19)
    f: Dict[str, object] = {}
    if mask & 0x2:
        f["position"] = read_compressed_vector(bs, 0.0005)
    if ctx.has_physics:
        if mask & 0x4:
            f["velocity"] = read_compressed_vector(bs, 0.001)
        if mask & 0x8:
            f["angular_velocity"] = read_compressed_vector2(bs, 0.001)
    if mask & 0x1:
        f["rotation"] = read_unit_quaternion(bs, 14)
    if ctx.has_physics:
        if mask & 0x4000:
            f["vec_80"] = read_compressed_vector(bs, 0.001)
            f["vec_8c"] = read_compressed_vector(bs, 0.001)
        if mask & 0x20:
            f["vec_44"] = read_compressed_vector(bs, 0.0001)
        if mask & 0x40:
            f["vec_68"] = read_compressed_vector(bs, 0.0001)
        if mask & 0x100:
            f["vec_50"] = read_compressed_vector(bs, 0.0001)
        if mask & 0x200:
            f["vec_74"] = read_compressed_vector(bs, 0.0001)
        if mask & 0x80:
            f["flag_9c"] = bs.read_bits(1) == 1
        if mask & 0x8000:
            f["flag_b0"] = bs.read_bits(1) == 1
    if mask & 0x10:
        if ctx.range_bits is None:
            raise UnsupportedLayout("mask 0x10 needs the component range of the template")
        f["range_value"] = bs.read_bits(ctx.range_bits)
    if mask & 0x400:
        f["bits_9d"] = bs.read_bits(2)
    if ctx.is_player_control:
        if ctx.is_parachute:
            if mask & 0x2000:
                f["parachute_state"] = bs.read_bits(width_for(8))
        else:
            if mask & 0x800:
                f["weapon_0"] = bs.read_bits(width_for(9)) - 1
            if mask & 0x1000:
                f["weapon_1"] = bs.read_bits(width_for(9)) - 1
            if mask & 0x20000:
                f["weapon_2"] = bs.read_bits(width_for(9)) - 1
            if mask & 0x10000:
                f["bits_b4"] = bs.read_bits(width_for(0x10))
            if mask & 0x40000:
                f["flag_b8"] = bs.read_bits(1) == 1
    return SimpleObjectUpdate(mask, f, bs.bit_pos - start)


@dataclass
class SoldierUpdate:
    """``SoldierNetworkable::setNetUpdate`` @ 0x08249860 (21-bit mask, not-StatePrecisionFull path)."""

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0
    ragdoll: bool = False


def decode_soldier(bs: BitStream, weapon_bits: int = 4, ragdoll_bones: int = 3) -> SoldierUpdate:
    """Port of the soldier state reader.

    ``weapon_bits``: width of the mask-0x1000 field, ``width_for(soldierTemplate.vtable[+0x168]() + 2)``; the
    template getter is not in the template files yet, so callers pass the width that makes records exact.
    ``weapon_bits`` is 4 for every soldier template of the samples (233061 of 233061 records explained exactly).
    When mask bit 0x8000 (ragdoll) is set the record carries ``RagDoll::readCurrentState`` instead of the walking state.
    """
    start = bs.bit_pos
    mask = bs.read_bits(21)
    f: Dict[str, object] = {}
    if mask & 0x40:
        f["stance_8"] = bs.read_bits(8)                      # pfVar6[0x17] (scaled by the component at +0x3c)
        f["stance_flag"] = bs.read_bits(1) == 1              # pfVar6[0x18]
    if mask & 0x20:
        f["pose"] = bs.read_bits(width_for(5))               # Soldier+0x1fc getPose (current stance)
        f["requested_pose"] = bs.read_bits(width_for(5))     # Soldier+0x200 getRequestedPose
    if mask & 0x8000:
        # RagDoll::readCurrentState 0x08347030: 9 bits, bone 0 as three raw floats (its world position), then one
        # readCompressedVector2 per further enabled bone. Every soldier of the samples has exactly 3 further bones.
        f["ragdoll_state"] = bs.read_bits(9)          # number of bits the particles took
        root = _raw_floats(bs)
        f["ragdoll_root"] = root
        for i in range(ragdoll_bones):                # bones 6 (hips, = root), 1, 15, 31 are sent: ragdoll_net_boneEnable = 15
            f[f"ragdoll_bone_{i + 1}"] = read_compressed_vector2(bs, 0.01, root)
        return SoldierUpdate(mask, f, bs.bit_pos - start, ragdoll=True)
    if mask & 0x1:
        f["position"] = read_compressed_vector(bs, 0.0005)
    if mask & 0x80:
        f["velocity"] = read_compressed_vector(bs, 0.001)
    # angle_c/angle_d land in Soldier+0x214/+0x204 (no accessor; meaning unresolved)
    # 12-bit angles expanded to degrees (OpenBattlefield2 soldier layout notes): yaw +-360, pitch +-90, +-180, +-90
    for bit, name, span in ((0x2, "yaw", 360.0), (0x4, "pitch", 90.0), (0x8, "angle_c", 180.0), (0x10, "angle_d", 90.0)):
        if mask & bit:
            f[name] = (bs.read_bits(12) / 0xFFF * 2.0 - 1.0) * span
    f["state_3"] = bs.read_bits(width_for(4))                # pfVar6[0x20]
    f["state_2"] = bs.read_bits(width_for(2))                # pfVar6[0x21]
    f["is_sky_diving"] = bs.read_bits(1) == 1                # Soldier::setIsSkyDiving
    f["is_swimming"] = bs.read_bits(1) == 1                  # Soldier+0x2a0 getIsSwimming
    f["flag_7f"] = bs.read_bits(1) == 1                      # Soldier+0x38c (no accessor; unresolved)
    if mask & 0x400:
        f["aim_a"] = (bs.read_bits(10) / 0x3FF * 2.0 - 1.0) * 50.0      # expanded to +-50
    if mask & 0x800:
        f["aim_b"] = (bs.read_bits(10) / 0x3FF * 2.0 - 1.0) * 50.0
    f["flag_98"] = bs.read_bits(1) == 1                      # unconditional
    if mask & 0x4000:
        f["value_5"] = bs.read_bits(5)
    if mask & 0x1000:
        f["weapon_item_index"] = bs.read_bits(weapon_bits) - 1    # itemIndex of the weapon in hand, -1 none
    if mask & 0x2000:
        f["bits_2"] = bs.read_bits(2)
    if mask & 0x10000:
        f["ladder"] = bs.read_bits(width_for(0x100))
        if f["ladder"]:
            f["ladder_pos"] = bs.read_bits(12) / 0xFFF
    if mask & 0x100000:
        f["zipline"] = bs.read_bits(16)
        if f["zipline"]:
            f["zipline_pos"] = bs.read_bits(12) / 0xFFF
    if mask & 0x80000:
        f["value_4"] = bs.read_bits(width_for(0x10))
    return SoldierUpdate(mask, f, bs.bit_pos - start)


def decode_simple_object_pose(bs: BitStream, has_physics: bool) -> SimpleObjectUpdate:
    """Only the leading part of ``SimpleObjectNetworkable``: mask, position, velocities and rotation.

    Everything after the rotation depends on template facts (health field width ...), but position and rotation are
    always first, and positions of all samples are absolute float32 triples (mode 0), so a pose can be read for
    every world object without knowing the rest of the body.
    """
    start = bs.bit_pos
    mask = bs.read_bits(19)
    f: Dict[str, object] = {}
    if mask & 0x2:
        f["position"] = read_compressed_vector(bs, 0.0005)
    if has_physics:
        if mask & 0x4:
            f["velocity"] = read_compressed_vector(bs, 0.001)
        if mask & 0x8:
            f["angular_velocity"] = read_compressed_vector2(bs, 0.001)
    if mask & 0x1:
        f["rotation"] = read_unit_quaternion(bs, 14)
    return SimpleObjectUpdate(mask, f, bs.bit_pos - start)


@dataclass
class ProjectileUpdate:
    """``GenericProjectileNetworkable::setNetUpdate`` @ 0x082386e0 (5-bit mask)."""

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_generic_projectile(bs: BitStream, range_bits: Optional[int] = None) -> ProjectileUpdate:
    start = bs.bit_pos
    mask = bs.read_bits(5)
    f: Dict[str, object] = {}
    if mask & 0x2:
        f["position"] = read_compressed_vector(bs, 0.0005)
    if mask & 0x1:
        f["rotation"] = read_unit_quaternion(bs, 12)         # 4 x 12 bits (verified: 14 over-reads by 8 bits)
    if mask & 0x4:
        f["flag_24"] = bs.read_bits(1) == 1
        if f["flag_24"]:
            negative = bs.read_bits(1) == 1
            magnitude = bs.read_bits(15)
            f["value_28"] = -magnitude if negative else magnitude
            f["velocity"] = read_high_compressed_vector(bs, 0.001)
            f["flag_48"] = bs.read_bits(1) == 1
            if f["flag_48"]:
                f["value_4c"] = bs.read_bits(16)
    if mask & 0x10:
        if range_bits is None:
            raise UnsupportedLayout("mask 0x10 needs the component range of the template")
        f["range_value"] = bs.read_bits(range_bits)
    return ProjectileUpdate(mask, f, bs.bit_pos - start)


@dataclass
class EngineUpdate:
    """``EngineNetworkable::setNetUpdate`` @ 0x08234e80 (11-bit mask; fields by mask bit)."""

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_engine(bs: BitStream, gear_bits: int = 0, flag_20: bool = False, flag_80: bool = False) -> EngineUpdate:
    """``gear_bits`` = width_for(engine.numGears + 1) (0 when the template value is -1), ``flag_20``/``flag_80`` are bits of
    the engine's type flags (raw call offset +0x1ac) that enable mask bits 0x100 and 0x400."""
    start = bs.bit_pos
    mask = bs.read_bits(11)
    f: Dict[str, object] = {}
    if mask & 0x2:
        f["gear"] = bs.read_bits(gear_bits)
    for bit, name in ((0x4, "rpm_a"), (0x8, "rpm_b"), (0x10, "throttle")):
        if mask & bit:
            f[name] = bs.read_bits(16) / 0xFFFF * 2.0 - 1.0
    for bit, name in ((0x20, "analog_20"), (0x40, "analog_40"), (0x80, "analog_80")):
        if mask & bit:
            f[name] = bs.read_bits(12) / 0xFFF * 2.0 - 1.0
    if flag_20 and mask & 0x100:
        f["value_100"] = bs.read_bits(16) / 0xFFFF
    if mask & 0x200:
        f["flag_2c"] = bs.read_bits(1) == 1
        f["flag_2d"] = bs.read_bits(1) == 1
    if flag_80 and mask & 0x400:
        sign = bs.read_bits(1) == 1
        f["value_400"] = (-1 if sign else 1) * bs.read_bits(16) / 0xFFFF
        f["tail_8"] = bs.read_bits(8)                        # +0x38, /255 (only inside the 0x400 block)
        f["tail_flag"] = bs.read_bits(1) == 1
        f["tail_2"] = bs.read_bits(2)
    return EngineUpdate(mask, f, bs.bit_pos - start)


@dataclass
class RotationalBundleUpdate:
    """``RotationalBundleNetworkable::setNetUpdate`` @ 0x0823fb30 (7-bit mask)."""

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_rotational_bundle(bs: BitStream, field_bits: int) -> RotationalBundleUpdate:
    """Six rotation/velocity values of ``field_bits`` bits each (mask 0x1..0x20) and a 16-bit value (0x40).
    ``field_bits`` comes from the template's rotational bundle info (0x20 means raw float32)."""
    start = bs.bit_pos
    mask = bs.read_bits(7)
    f: Dict[str, object] = {}
    for bit, name in ((0x1, "rot_x"), (0x2, "rot_y"), (0x4, "rot_z"), (0x8, "vel_x"), (0x10, "vel_y"), (0x20, "vel_z")):
        if mask & bit:
            f[name] = bs.read_bits(field_bits)
    if mask & 0x40:
        f["state"] = bs.read_bits(16)
    return RotationalBundleUpdate(mask, f, bs.bit_pos - start)


@dataclass
class SpringUpdate:
    """``SpringNetworkable::setNetUpdate`` @ 0x0824c660: 1 presence bit, then two high-compressed vectors."""

    present: bool
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_spring(bs: BitStream, has_extra: bool = False) -> SpringUpdate:
    """``has_extra``: the optional trailing ``bit [+ 16 bits]`` that exists when the spring's component reports flag 8."""
    start = bs.bit_pos
    present = bs.read_bits(1) == 1
    f: Dict[str, object] = {}
    if present:
        f["position"] = read_high_compressed_vector(bs, 0.001)
        f["velocity"] = read_high_compressed_vector(bs, 0.001)
        if has_extra and bs.read_bits(1) == 1:
            f["extra"] = bs.read_bits(16)
    return SpringUpdate(present, f, bs.bit_pos - start)


def decode_pco_slots(bs: BitStream) -> Dict[str, object]:
    """``PlayerControlObjectNetworkable::setNetUpdate`` (0x0823e320) branch for a root without wrapped child:
    4-bit mask; bits 1, 2, 4 carry a ``width_for(9)``-bit weapon index each, bit 8 a 1-bit flag."""
    mask = bs.read_bits(4)
    f: Dict[str, object] = {"mask": mask}
    for bit, name in ((1, "slot_0"), (2, "slot_1"), (4, "slot_2")):
        if mask & bit:
            f[name] = bs.read_bits(width_for(9))
    if mask & 8:
        f["flag"] = bs.read_bits(1) == 1
    return f


@dataclass
class DestroyableUpdate:
    """``DestroyableObjectNetworkable::setNetUpdate`` @ 0x08232c40 (2-bit mask)."""

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_destroyable(bs: BitStream, range_bits: int) -> DestroyableUpdate:
    start = bs.bit_pos
    mask = bs.read_bits(2)
    f: Dict[str, object] = {}
    if mask & 1:
        f["range_value"] = bs.read_bits(range_bits)
    if mask & 2:
        f["vec"] = read_compressed_vector(bs, 0.001)
    return DestroyableUpdate(mask, f, bs.bit_pos - start)


#: ``operator<<(ostream&, EngineType)`` (server 0x082a3c10): value of ``setEngineType``. EngineNetworkable::setNetUpdate tests
#: bit 0x20 of it (mask 0x100 block, helicopters) and bit 0x80 (mask 0x400 block, c_ETNewCar2).
ENGINE_TYPES = {"c_ETPlane": 1, "c_ETCar": 2, "c_ETTank": 6, "c_ETShip": 9, "c_ETRocket": 0x11, "c_ETTorpedo": 0x19,
                "c_ETHelicopter": 0x21, "c_ETNewCar": 0x42, "c_ETNewTank": 0x46, "c_ETNewCar2": 0xc2}


#: ``EngineTemplate::numberOfGears`` when the template does not call ``setNumberOfGears`` (constructor 0x082a3ce0, member +0x3c8).
ENGINE_DEFAULT_GEARS = 1


def _decode_elements(bs: BitStream, seq: str, elements, range_bits: int, rb_bits: int = 12, parts: Optional[list] = None) -> None:
    """``elements``: one info dict per letter of ``seq`` (``TemplateInfo.engines``); decoded updates are appended to ``parts``
    as ``(letter, raw update, element info)`` when a list is given."""
    for index, letter in enumerate(seq):
        info = elements[index] if elements and index < len(elements) else {}
        update = None
        if letter == "R":
            update = decode_rotational_bundle(bs, rb_bits)
        elif letter == "E":
            gears = info.get("gears")
            gears = ENGINE_DEFAULT_GEARS if gears is None else gears      # EngineTemplate ctor 0x082a3ce0: +0x3c8 = 1
            etype = ENGINE_TYPES.get(info.get("type"), 0)
            update = decode_engine(bs, width_for(gears + 1) if gears != -1 else 0, bool(etype & 0x20), bool(etype & 0x80))
        elif letter == "S":
            update = decode_spring(bs)
        elif letter == "D":
            update = decode_destroyable(bs, range_bits)
        elif letter == "O":
            obj = info.get("object", {})
            # a Rotor is a child of the PlayerControlObject: the weapon-slot fields of the full-state record exist (verified bit-exactly)
            update = decode_simple_object(bs, SimpleObjectContext(obj.get("mobile", True), width_for(obj.get("range_total", 0)), True))
        if parts is not None:
            parts.append((letter, update, info))


def decode_vehicle(bs: BitStream, template, rb_bits: int = 12, parts: Optional[list] = None) -> int:
    """Decode the ghost body of a PlayerControlObject root (SimpleObject + the networkable sequence derived from its template
    tree, ``TemplateInfo.netseq``) and return the number of bits consumed. Letters: R rotational bundle (12-bit fields),
    E engine, S spring, D destroyable object, O simple object (Rotor). ``parts`` (optional list) receives
    ``("P", simple object update, {})`` followed by one ``(letter, update, element info)`` per element."""
    start = bs.bit_pos
    root = decode_simple_object(bs, SimpleObjectContext(bool(template.mobile), template.range_bits, True,
                                                        template.cls.lower() == "parachute"))
    if parts is not None:
        parts.append(("P", root, {}))
    _decode_elements(bs, template.netseq, template.engines, template.range_bits, rb_bits, parts)
    return bs.bit_pos - start


def decode_child_pco(bs: BitStream, root_template, index: int, parts: Optional[list] = None) -> int:
    """Ghost body of the ``index``-th nested PlayerControlObject (turret / gunner seat / passenger seat) of a vehicle: the
    ghost id is ``root id + 1 + index``. Returns the number of bits consumed.

    ``PlayerControlObjectNetworkable::setNetUpdate`` (0x0823e320) has two forms, chosen by ``IPlayerControlObject::getOwnCameras()``:
    a PCO that owns a camera (gunner seats) sends the 4-bit weapon block (``decode_pco_slots``) followed by its own derived
    sequence; a PCO without camera (passenger seats) sends an 11-bit length and then the wrapped networkable of the occupant,
    a ``SoldierNetworkable`` (verified: 290 of 290 bits on the 301-bit records of jep_vodnik / the_mi17 / hmmwv seats).
    """
    start = bs.bit_pos
    seq, elements, has_camera = root_template.pco_children[index]
    if has_camera:
        slots = decode_pco_slots(bs)
        if parts is not None:
            parts.append(("P", slots, {}))
        _decode_elements(bs, seq, elements, root_template.range_bits, 12, parts)
        return bs.bit_pos - start
    length = bs.read_bits(11)
    if length:
        payload_start = bs.bit_pos
        soldier = decode_soldier(bs)
        if bs.bit_pos - payload_start != length:
            raise UnsupportedLayout("seat payload is not a soldier state")
        if parts is not None:
            parts.append(("W", soldier, {}))
    return bs.bit_pos - start


@dataclass
class OverheadCameraUpdate:
    """``OverheadCameraNetworkable::setNetUpdate`` @ 0x0823c870 (commander's overhead camera; 4-bit mask).

    0x1 two bytes ``move_a``, ``move_b`` (each ``2 * byte / 255 - 1`` times ``OverheadCamera::getMaxSpeed``, dead zone near 0),
    0x2 position (``readCompressedVector2``, scale 0.001), 0x4 signed 7-bit value stored at camera +0x20c, 0x8 enabled flag.
    """

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_overhead_camera(bs: BitStream) -> OverheadCameraUpdate:
    start = bs.bit_pos
    mask = bs.read_bits(4)
    f: Dict[str, object] = {}
    if mask & 1:
        f["move_a"] = bs.read_bits(8) / 255.0 * 2.0 - 1.0
        f["move_b"] = bs.read_bits(8) / 255.0 * 2.0 - 1.0
    if mask & 2:
        f["position"] = read_compressed_vector2(bs, 0.001)
    if mask & 4:
        negative = bs.read_bits(1) == 1
        value = bs.read_bits(7)
        f["value_20c"] = -value if negative else value
    if mask & 8:
        f["enabled"] = bs.read_bits(1) == 1
    return OverheadCameraUpdate(mask, f, bs.bit_pos - start)


def _signed_unit(raw: int, bits: int) -> float:
    """``2 * raw / (2^bits - 1) - 1`` with the dead zone ``2 / (2^bits - 1)`` around zero that the readers apply
    (``RotationalBundleNetworkable`` compares against ``2.0 / mask``, ``EngineNetworkable`` against 3.05e-5 / 4.88e-4)."""
    top = (1 << bits) - 1
    value = raw / top * 2.0 - 1.0
    return value if abs(value) > 2.0 / top else 0.0


def rotational_bundle_units(update: RotationalBundleUpdate, field_bits: int, info: Dict[str, object]) -> Dict[str, float]:
    """Physical values of a rotational bundle update (``RotationalBundleNetworkable::setNetUpdate`` 0x0823fb30).

    ``rot_x/y/z``: rotation in degrees = normalised value * 180 (``DAT 0x08891074``). ``vel_x/y/z``: normalised value *
    ``|setMaxSpeed axis|`` * 16 (``DAT 0x0888b160``; the unit is the one of the template's max speed). ``state``: raw 16 bit value.
    """
    out: Dict[str, float] = {}
    speeds = info.get("max_speed") or [0.0, 0.0, 0.0]
    for index, axis in enumerate("xyz"):
        if f"rot_{axis}" in update.fields:
            out[f"rot_{axis}"] = _signed_unit(update.fields[f"rot_{axis}"], field_bits) * 180.0
        if f"vel_{axis}" in update.fields:
            out[f"vel_{axis}"] = _signed_unit(update.fields[f"vel_{axis}"], field_bits) * abs(speeds[index]) * 16.0
    if "state" in update.fields:
        out["state"] = update.fields["state"]
    return out


def engine_units(update: EngineUpdate, info: Dict[str, object]) -> Dict[str, float]:
    """Engine update values scaled the way ``EngineNetworkable::setNetUpdate`` (0x08234e80) stores them.

    ``rpm_a`` (+0x18) and ``throttle`` (+0x14) are normalised values * 1.25 * max(|min z|, |max z|) of the engine's rotation limits,
    ``rpm_b`` (+0x1c) uses the x limits; ``analog_20/40/80`` (+0x20/+0x24/+0x10) are normalised values * 1.25. The names of the
    fields are the offsets' positions in the decoder, not confirmed game names.
    """
    limits = info.get("limits") or [0.0, 0.0]
    out: Dict[str, float] = {}
    f = update.fields
    for name, key, limit in (("rpm_a", "rpm_a", limits[0]), ("rpm_b", "rpm_b", limits[1]), ("throttle", "throttle", limits[0])):
        if name in f:
            value = f[name]            # decode_engine already returned raw / 0xffff * 2 - 1
            out[key] = (value if abs(value) > 3.0518e-5 else 0.0) * 1.25 * limit        # dead zone _DAT_088b28d4
    for name in ("analog_20", "analog_40", "analog_80"):
        if name in f:
            out[name] = (f[name] if abs(f[name]) > 4.884e-4 else 0.0) * 1.25                # dead zone _DAT_088b2dd8
    for name in ("gear", "value_100", "flag_2c", "flag_2d", "value_400", "tail_8", "tail_flag", "tail_2"):
        if name in f:
            out[name] = f[name]
    return out


@dataclass
class TriggerableTargetUpdate:
    """``TriggerableTargetNetworkable::setNetUpdate`` @ 0x0824e3f0 (4-bit mask; moving map parts such as the Special Forces elevators).

    0x1 position (``TriggerableTarget::setPos``), 0x2 rotation (``setRot``, Euler vector), 0x4 / 0x8 a value of ``width_for(0x42)``
    bits minus one, stored at object +0x14c / +0x154 (-1 = keep).
    """

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_triggerable_target(bs: BitStream) -> TriggerableTargetUpdate:
    start = bs.bit_pos
    mask = bs.read_bits(4)
    f: Dict[str, object] = {}
    if mask & 1:
        f["position"] = read_compressed_vector(bs, 0.001)
    if mask & 2:
        f["rotation"] = read_compressed_vector(bs, 0.001)
    if mask & 4:
        f["value_14c"] = bs.read_bits(width_for(0x42)) - 1
    if mask & 8:
        f["value_154"] = bs.read_bits(width_for(0x42)) - 1
    return TriggerableTargetUpdate(mask, f, bs.bit_pos - start)
