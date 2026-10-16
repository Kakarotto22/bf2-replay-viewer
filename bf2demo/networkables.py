"""Networkable state decoders for ghost update records.

A ghost update (``GhostManager::readData`` action 1) carries ``length`` bits
of state that ``io::NetworkManager::setNetUpdate`` (0x0809c130) hands to the
object's networkables. Each decoder below mirrors one
``<Class>Networkable::setNetUpdate`` and reports how many bits it consumed so
callers can verify it against the record length.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .bitstream import BitStream


def _signed3(bs: BitStream) -> int:
    negative = bs.read_bits(1) == 1
    mag = bs.read_bits(3)
    return -mag if negative else mag


def _unit16(bs: BitStream) -> float:
    """16-bit value mapped to [-1.25, 1.25] with a ~3e-5 dead zone."""
    v = bs.read_bits(16) / 65535.0 * 2.0 - 1.0
    return (v if abs(v) > 3.051804378628731e-05 else 0.0) * 1.25


@dataclass
class ControlPointUpdate:
    """``ControlPointNetworkable::setNetUpdate`` @ 0x08231880.

    7-bit change mask, each set bit followed by its field:

    ======  ==============================================  =========================
    bit     wire                                            applied via
    ======  ==============================================  =========================
    0x01    sign(1)+mag(3)                                  ``ControlPoint::setTeam``
    0x02    bool(1)                                         ControlPoint+0x158
    0x04    2 x unit16 (take-over level, change per sec)    +0x154 / ``setTakeOverChangePerSecond``
    0x08    sign(1)+mag(3) != 0                             ``setAllowCaptureByTeam(0)``
    0x10    sign(1)+mag(3) != 0                             ``setAllowCaptureByTeam(1)``
    0x20    sign(1)+mag(3)                                  ``setFlag`` (raised flag team)
    0x40    sign(1)+mag(3)                                  ``setCapturingState``
    ======  ==============================================  =========================
    """

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_control_point(data: bytes, bit_start: int) -> ControlPointUpdate:
    bs = BitStream(data, bit_start)
    mask = bs.read_bits(7)
    f: Dict[str, object] = {}
    if mask & 0x01:
        f["team"] = _signed3(bs)
    if mask & 0x02:
        f["area_value_active"] = bs.read_bits(1) == 1       # ControlPoint+0x158: gates getAreaValueTeam1/2 (template areaValue of each team)
    if mask & 0x04:
        f["take_over"] = _unit16(bs)
        f["take_over_per_second"] = _unit16(bs)
    if mask & 0x08:
        f["allow_capture_team1"] = _signed3(bs) != 0
    if mask & 0x10:
        f["allow_capture_team2"] = _signed3(bs) != 0
    if mask & 0x20:
        f["flag_team"] = _signed3(bs)
    if mask & 0x40:
        f["capturing_state"] = _signed3(bs)
    return ControlPointUpdate(mask, f, bs.bit_pos - bit_start)


def _width_for(count: int) -> int:
    n = 0
    if count:
        while (1 << n) - 1 < count:
            n += 1
    return n


def _signed_mag(bs: BitStream, bits: int) -> int:
    negative = bs.read_bits(1) == 1
    mag = bs.read_bits(bits)
    return -mag if negative else mag


@dataclass
class PlayerUpdate:
    """``Player::setNetUpdate`` @ 0x080f11c0 (28-bit change mask, fields in this order).

    Field meaning comes from the setters called when the update is applied
    (``Player::setIsAlive``, ``setSpawnGroup``, ``setTeam``, ``setKit``, ``setSquadId`` ...).
    """

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_player(data: bytes, bit_start: int) -> PlayerUpdate:
    bs = BitStream(data, bit_start)
    mask = bs.read_bits(28)
    f: Dict[str, object] = {}
    if mask & 0x1:
        f["alive"] = bs.read_bits(1) == 1                       # setIsAlive
    if mask & 0x2:
        f["spawn_group"] = bs.read_bits(_width_for(0x100))      # setSpawnGroup
    if mask & 0x8:                      # PlayerScoreData (names from pmgr_getScore/pmgr_setScore: psd+0 score,
        f["score"] = _signed_mag(bs, 11)                        # psd+0x00 score
        f["deaths"] = bs.read_bits(_width_for(0x800))           # psd+0x10 deaths
        f["kills"] = bs.read_bits(_width_for(0x800))            # psd+0x14 kills
        f["teamwork"] = _signed_mag(bs, 11)                      # psd+0x04 rplScore (teamwork: assists, revives, TK, suicide)
        f["teamkills"] = bs.read_bits(_width_for(0x800))        # psd+0x18 TKs
    if mask & 0x200000:
        f["flag_holder"] = bs.read_bits(1) == 1                 # setFlagHolder
    if mask & 0x10:
        f["call_for_medic"] = bs.read_bits(1) == 1              # setCallForMedic
    if mask & 0x2000000:
        f["firing_mode"] = bs.read_bits(2)
    weapons = []
    for i, m in enumerate((0x40, 0x80, 0x20000)):               # primary / alt / flare firing slots
        if (mask & m) or (mask & 0x10000):
            slot = {"firing": bs.read_bits(1) == 1}
            if slot["firing"] or (mask & 0x10000):
                slot["ammo_index"] = bs.read_bits(_width_for(0x40)) - 1
                slot["v2"] = bs.read_bits(2)
                slot["v1"] = bs.read_bits(1)
                if bs.read_bits(1) == 1:
                    slot["charge"] = bs.read_bits(8) / 255.0
                else:
                    slot["charge"] = bs.read_bits(6) / 63.0
                slot["v4"] = bs.read_bits(4)
            weapons.append((i, slot))
    if weapons:
        f["weapon_slots"] = dict(weapons)
    if mask & 0x40000:
        f["sprinting"] = bs.read_bits(1) == 1                   # setSprintState
        f["sprinting_last_tick"] = bs.read_bits(1) == 1       # setSprintStateLastTick
    if mask & 0x100:
        f["ping"] = bs.read_bits(_width_for(0x400))              # getPing (Player+0x118 on the server)
    if mask & 0x20:
        f["spawn_tick"] = bs.read_bits(32)                       # tick the player may spawn at (getTimeToSpawn)
        f["man_down"] = bs.read_bits(1) == 1                       # Player+0xcc
    if mask & 0x200:
        f["team"] = bs.read_bits(_width_for(4)) - 1             # setTeam
    if mask & 0x400:
        f["camera"] = bs.read_bits(_width_for(9))                  # baseline +0x2c, handed to Player::getCamera()
        f["camera_flag"] = bs.read_bits(1) == 1                   # baseline +0xae; setNetUpdate stores it but never applies it (meaning unknown)
    if mask & 0x800:
        f["time_outside_world"] = bs.read_bits(_width_for(0x100))   # Player+0x24c getTimeOutSideWorld: how long the player has been outside the CombatArea (raw byte, unit unverified)
    if mask & 0x1000:
        kit = bs.read_bits(_width_for(0x100))                   # setKit(low nibble)
        f["kit"] = kit & 0xF
        f["kit_hi"] = kit >> 4
    if mask & 0x2000:
        f["squad_id"] = bs.read_bits(_width_for(0x10))          # setSquadId
    if mask & 0x4000:
        f["rank"] = bs.read_bits(_width_for(0x20)) - 1          # PlayerScoreData::setRank
        f["first_places"] = bs.read_bits(_width_for(0x100))      # psd+0x54 (pmgr_getScore firstPlace)
        f["second_places"] = bs.read_bits(_width_for(0x100))     # psd+0x58
        f["third_places"] = bs.read_bits(_width_for(0x100))      # psd+0x5c
    if mask & 0x8000:
        f["free_camera"] = bs.read_bits(1) == 1
    if mask & 0x400000:
        f["overhead_camera"] = bs.read_bits(1) == 1
    if mask & 0x800000:
        f["squad_invite_mask"] = bs.read_bits(8)                 # Player+0x11c getSquadInviteMask: bit n = invited by squad n
    if mask & 0x1000000:
        f["killed_by"] = bs.read_bits(_width_for(0x10001)) - 1    # Player+0x314: id of the player who killed this one, -1 after respawn
    f["is_squad_leader"] = bs.read_bits(1) == 1                  # baseline +0x3c -> Player+0xf5 getIsSquadLeader (always sent)
    if mask & 0x4000000:
        commander = bs.read_bits(1) == 1                        # setIsCommander
        f["commander"] = commander
        if commander:
            f["commander_flags"] = [bs.read_bits(1) == 1 for _ in range(5)]
            f["commander_analog"] = [bs.read_bits(8) / 255.0 for _ in range(3)]
    f["is_connected"] = bs.read_bits(1) == 1                     # Player+0x17c getIsConnected
    if mask & 0x8000000:
        f["mask_setting"] = bs.read_bits(_width_for(4))         # setMaskSetting
    return PlayerUpdate(mask, f, bs.bit_pos - bit_start)


@dataclass
class ScoreManagerUpdate:
    """``ScoreManager::setNetUpdate`` (client 0x5c9650, server 0x0810a5d0): 32-bit mask, then 18 bits per set bit.

    Bits 0x400 (team 1) and 0x400000 (team 2) are the team tickets: tickets(18), flag(1), ticket state(18)
    (OpenBattlefield2 docs/functions/score-manager.md); the other thirty are further score numbers.
    """

    mask: int
    values: Dict[int, object] = field(default_factory=dict)
    bits: int = 0

    @property
    def tickets(self) -> Dict[int, int]:
        """``{team: tickets}`` carried by this update."""
        out = {}
        if 10 in self.values:
            out[1] = self.values[10][0]
        if 22 in self.values:
            out[2] = self.values[22][0]
        return out


def _read_signed(bs: BitStream, bits: int) -> int:
    """Sign bit then magnitude (the ``readBits(1)`` / ``readBits(n)`` / negate pattern used by ``ScoreManager::setNetUpdate``)."""
    negative = bs.read_bits(1) == 1
    value = bs.read_bits(bits)
    return -value if negative else value


#: Per mask bit of ``ScoreManager::setNetUpdate`` (0x0810a5d0, field list recovered from every ``readBits`` of the function):
#: one signed 17-bit number by default; bits 4, 16, 24, 25 carry two of them; the ticket bits 10 and 22 carry a number, a flag and a
#: second number; bit 30 a signed 2-bit number; bit 31 a signed 2-bit number and two signed 17-bit numbers.
_SCORE_DOUBLE = (4, 16, 24, 25)
_SCORE_TICKETS = (10, 22)


def decode_score_manager(data: bytes, bit_start: int) -> ScoreManagerUpdate:
    bs = BitStream(data, bit_start)
    mask = bs.read_bits(32)
    values: Dict[int, object] = {}
    for bit in range(32):
        if mask >> bit & 1:
            if bit in _SCORE_TICKETS:
                first = _read_signed(bs, 17)
                flag = bs.read_bits(1)
                values[bit] = (first, flag, _read_signed(bs, 17))
            elif bit in _SCORE_DOUBLE:
                values[bit] = (_read_signed(bs, 17), _read_signed(bs, 17))
            elif bit == 30:
                values[bit] = _read_signed(bs, 2)
            elif bit == 31:
                values[bit] = (_read_signed(bs, 2), _read_signed(bs, 17), _read_signed(bs, 17))
            else:
                values[bit] = _read_signed(bs, 17)
    return ScoreManagerUpdate(mask, values, bs.bit_pos - bit_start)


@dataclass
class SpawnGroupUpdate:
    """``SpawnGroup::setNetUpdate`` (server 0x08111e90): 6-bit mask. The ghost id is the ``object_id`` of ``CreateSpawnGroupEvent``.

    0x01 minimap position (two bytes ``x, z``; world = ``GLSWorldSize * byte / 255 - GLSWorldSize / 2``, ``setPos``),
    0x02 team (4 bits, ``setTeam``), 0x04 active (``setActive``), 0x08 only_for_ai (member +0x6e, read by ``getActive(false)`` beside ``onlyForHuman`` +0x6f),
    0x10 has_spawn_points (member +0x74, set by ``addSpawnPoint``), 0x20 squad (8 bits, value - 1, ``setSquad``).
    """

    mask: int
    fields: Dict[str, object] = field(default_factory=dict)
    bits: int = 0


def decode_spawn_group(data: bytes, bit_start: int) -> SpawnGroupUpdate:
    bs = BitStream(data, bit_start)
    mask = bs.read_bits(6)
    f: Dict[str, object] = {}
    if mask & 0x10:
        f["has_spawn_points"] = bs.read_bits(1) == 1
    if mask & 0x2:
        f["team"] = bs.read_bits(4)
    if mask & 0x4:
        f["active"] = bs.read_bits(1) == 1
    if mask & 0x8:
        f["only_for_ai"] = bs.read_bits(1) == 1
    if mask & 0x1:
        f["map_x"] = bs.read_bits(8)
        f["map_z"] = bs.read_bits(8)
    if mask & 0x20:
        f["squad"] = bs.read_bits(8) - 1
    return SpawnGroupUpdate(mask, f, bs.bit_pos - bit_start)
