"""Refractor 2 ``GameEvent`` deserializers.

Every layout here is transcribed from the ``<Class>::deSerialize`` function in
``bf2_ia32`` (Linux dedicated server 1.5.3153, Ghidra 12.1.4). Event ids are
the ``GE<Name>`` globals returned by each ``<Class>::getType``.

``GameEventManager::readGameEvent`` (0x0808fd60) reads the event id with
``n`` bits where ``n`` is the smallest width with ``2**n - 1 >= registry[0x20]``.
``Game::registerGameEvents`` (0x08057af0) registers 63 makers with ids up to
69; the width is 7 bits, i.e. ``registry[0x20]`` tracks the highest id. Verified
on every sample: with 7-bit ids every packet is consumed to within its final
padding byte (6-bit ids desynchronise immediately).

Events carry no length prefix: an unknown or mis-decoded event makes the rest
of the packet's event block unreadable, which is why every registered event is
implemented here rather than only the interesting ones.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .bitstream import BitStream, Vec3

#: Highest event id registered by ``Game::registerGameEvents`` (FixPlayerTeam).
MAX_EVENT_ID = 69


def width_for(count: int) -> int:
    """Bit width used by Refractor for a value range ``[0, count]``.

    Mirrors the ``do { n++; } while ((1 << n) - 1 < count)`` idiom that
    appears throughout the deserializers.
    """
    n = 0
    if count:
        while (1 << n) - 1 < count:
            n += 1
    return n


EID_BITS = width_for(MAX_EVENT_ID)

#: ``BitStream::m_compressionVectorBitTable`` (0x0898cb64).
COMPRESSION_BIT_TABLE = (32, 20, 16, 12)

EVENT_NAMES: Dict[int, str] = {
    1: "Challenge", 2: "ChallengeResponse", 3: "ConnectionType", 4: "DataBlock",
    5: "CreatePlayer", 6: "CreateObject", 7: "DestroyObject", 8: "DestroyPlayer",
    9: "EnterVehicle", 10: "ExitVehicle", 11: "PostRemote", 12: "ChangePlayerName",
    13: "HandleDrop", 14: "HandlePickup", 15: "StringBlock", 16: "JoinSquad",
    17: "LeaveSquad", 19: "Commander", 20: "RadioMessage", 21: "KilledBy",
    22: "ChangeSquadName", 23: "SetPrivateSquad", 24: "IssueSquadOrder",
    25: "Invite", 26: "Rank", 27: "SetAcceptOrder", 28: "SetSquadLeader",
    29: "Spotted", 30: "Artillery", 31: "CreateKit", 32: "StickyProjectile",
    34: "AmbientEffectArea", 35: "VoipOnOff", 36: "CommanderCam", 37: "SupplyDrop",
    38: "VoipPlayerMute", 39: "Vote", 40: "ToggleFreeCamera", 41: "Medal",
    42: "Unlock", 43: "MissileInit", 45: "UAV", 46: "ContentCheck",
    47: "TargetDirection", 48: "EndOfRound", 49: "PythonCommand", 50: "Request",
    51: "DropVehicle", 54: "VoipSession", 55: "KickBan", 56: "BeginRound",
    57: "CreateSpawnGroup", 58: "RemoveSpawnGroup", 59: "UpdateTrigger",
    60: "GrapplingHookContainerCreate", 61: "GrapplingHookContainerUpdate",
    62: "GrapplingHookContainerDetach", 63: "GrapplingHookCreate",
    64: "GrapplingHookUpdate", 65: "PlayerTearGassed", 66: "SetNightVision",
    68: "VerifyPlayerTeam", 69: "FixPlayerTeam",
}


class EventReadError(Exception):
    """Raised when an event cannot be deserialized."""


@dataclass
class GameEvent:
    """One decoded event. ``fields`` keeps wire order."""

    eid: int
    name: str
    fields: Dict[str, object] = field(default_factory=dict)
    bit_start: int = 0
    bit_end: int = 0

    def __getitem__(self, key: str):
        return self.fields[key]

    def get(self, key: str, default=None):
        return self.fields.get(key, default)


# --------------------------------------------------------------------------- #
# Primitive readers (each mirrors a BitStream idiom seen in the decompilation)
# --------------------------------------------------------------------------- #

def _u(bs: BitStream, n: int) -> int:
    return bs.read_bits(n)


def _b(bs: BitStream) -> bool:
    return bs.read_bits(1) == 1


def _f32(bs: BitStream) -> float:
    return struct.unpack("<f", bs.read_bits(32).to_bytes(4, "little"))[0]


def _vec3(bs: BitStream) -> Vec3:
    return (_f32(bs), _f32(bs), _f32(bs))


def _signed(bs: BitStream, n: int) -> int:
    """``readBits(1)`` sign then ``readBits(n)`` magnitude (sign-magnitude)."""
    negative = _b(bs)
    mag = bs.read_bits(n)
    return -mag if negative else mag


def _raw(bs: BitStream, nbytes: int) -> bytes:
    return bytes(bs.read_bits(8) for _ in range(nbytes))


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin1")


def _str8(bs: BitStream) -> str:
    """uint8 length followed by that many bytes."""
    return _raw(bs, _u(bs, 8)).decode("latin1")


def read_compressed_vector(bs: BitStream, origin: Vec3 = (0.0, 0.0, 0.0),
                           scale: float = 1000.0) -> Vec3:
    """``BitStream::readCompressedVector`` @ 0x08432d30.

    ``mode(2)``: 0 -> three raw floats; otherwise each component is a sign bit
    plus ``table[mode]-1`` magnitude bits, scaled and offset by ``origin``.
    """
    mode = bs.read_bits(2)
    if mode == 0:
        return _vec3(bs)
    bits = COMPRESSION_BIT_TABLE[mode] - 1
    comps = [_signed(bs, bits) for _ in range(3)]
    return tuple(scale * c + o for c, o in zip(comps, origin))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Per-event deserializers. Comments give the deSerialize address and the
# object member each field is stored to (this+0xNN).
# --------------------------------------------------------------------------- #

def _challenge(bs):
    challenge = _raw(bs, 10)              # this+0xc (80 bits)
    text = _str8(bs)                      # this+0x27 len, this+0x17 data
    return {"challenge": challenge.hex(), "text": text}


def _challenge_response(bs):
    response = _raw(bs, 73)               # this+0xc (0x248 bits)
    return {"response": response.hex(), "value_a": _u(bs, 32), "value_b": _u(bs, 32),
            "value_c": _signed(bs, 31)}


def _connection_type(bs):
    return {"type": _u(bs, width_for(7))}


def _data_block(bs):
    is_header = _b(bs)                    # this+0xc
    if is_header:
        # Header announces a block: kind (0 server settings, 2 current game,
        # 5 map list) and its byte length; data chunks follow.
        return {"is_header": True, "kind": _u(bs, 32), "length": _u(bs, 32)}
    data = _raw(bs, _u(bs, 8))            # this+0x18 len, this+0x19 data
    return {"is_header": False, "data": data}


def _create_player(bs):  # 0x0806eb30
    f = {}
    f["team"] = _u(bs, 3)                 # this+0xc (Player::setTeam, verified against Player ghost team)
    f["spawn_group"] = _u(bs, 4)          # this+0xd: Player::getSpawnGroup (the constructor copies it; the client resets it with setSpawnGroup(0))
    f["is_remote"] = _b(bs)               # this+0xe
    f["player_id"] = _u(bs, 8)            # this+0x30
    f["ghost_id"] = _u(bs, 16)            # this+0x32 (id of the Player ghost)
    f["reserved"] = _u(bs, 16)            # this+0x34: the constructor always stores 0, executeClient never reads it
    f["is_ai"] = _b(bs)                   # this+0xf
    f["name"] = _cstr(_raw(bs, 32))       # this+0x10 (256 bits)
    return f


def _create_object(bs):  # 0x0806de70
    f = {"template_id": _u(bs, 32),       # this+0xc  (ObjectTemplate::getId)
         "object_id": _u(bs, 16),         # this+0x10
         "team": _u(bs, 2)}               # this+0x2c (PlayerControlObject team)
    multi = _b(bs)
    if multi:
        f["count"] = _u(bs, 8)            # this+0x30 multi-spawned object count
        f["position"] = f["rotation"] = None
    else:
        f["count"] = 1
        f["position"] = _vec3(bs) if _b(bs) else None   # this+0x14
        f["rotation"] = _vec3(bs) if _b(bs) else None   # this+0x20
    return f


def _destroy_object(bs):
    return {"object_id": _u(bs, 16)}


def _destroy_player(bs):
    return {"player_id": _u(bs, 8)}


def _enter_vehicle(bs):
    # EnterVehicleEvent::executeClient 0x08070f80 hands (player, object, flag) to the game client. The flag is True only when a player
    # takes the Soldier object that was created for them in the same tick (a spawn); entering a vehicle or a parachute is False
    # (302 of 302 soldier spawns and 0 of 800 vehicle entries in three samples).
    return {"player_id": _u(bs, 8), "object_id": _u(bs, 16), "is_spawn": _b(bs)}


def _exit_vehicle(bs):
    # ExitVehicleEvent::executeClient 0x08071230: (player, flag) to the game client; the flag is False in every sample
    return {"player_id": _u(bs, 8), "flag": _b(bs)}


def _post_remote(bs):
    # PostRemoteEvent::executeClient 0x08077c60: EventManager event (category ``kind``, id ``value``), raised ``delay`` seconds later
    f = {"kind": _u(bs, 4), "value": _u(bs, 32), "delay": _f32(bs)}
    n = _u(bs, 8)
    f["data"] = _raw(bs, n) if n else b""
    return f


def _change_player_name(bs):
    return {"player_id": _u(bs, 8), "name": _cstr(_raw(bs, 32))}


def _handle_drop(bs):
    return {"player_id": _u(bs, 8), "object_id": _u(bs, 16), "item_id": _u(bs, 16),
            "position": _vec3(bs)}


def _handle_pickup(bs):
    return {"player_id": _u(bs, 8), "object_id": _u(bs, 16), "item_id": _u(bs, 16)}


def _string_block(bs):
    is_header = _b(bs)
    if is_header:
        return {"is_header": True, "count": _u(bs, 8)}
    return {"is_header": False, "data": _raw(bs, _u(bs, 8))}


def _three_u8(bs):
    # Order verified against Player ghost squad ids: team, player, squad
    # (SquadManager::setSquadLeader(team, squad, player) is fed this+0xc, +0xe, +0xd).
    return {"team": _u(bs, 8), "player_id": _u(bs, 8), "squad_id": _u(bs, 8)}


def _leave_squad(bs):
    f = _three_u8(bs)
    f["flag"] = _b(bs)
    return f


def _commander(bs):
    # CommanderEvent::executeClient 0x0806c640: action 3 = SquadManager commander change(team = byte +0x10,
    # player = short +0x12, -1 none). The other actions (0,1,2,4,6,7,8) are client -> server requests.
    return {"action": _u(bs, width_for(9)), "team": _u(bs, 8), "player_id": _signed(bs, 15)}


def _radio_message(bs):
    # RadioMessageEvent::executeClient 0x08078dc0 copies every field unchanged into a RadioMessageReceivedEvent for the HUD;
    # ``unk_f`` (byte this+0xf) is copied but not interpreted there. Never seen in a sample.
    return {"player_id": _u(bs, 8), "target_id": _u(bs, 8), "kind": _u(bs, 2),
            "unk_f": _u(bs, 8), "message": _u(bs, width_for(0x13)),
            "variant": _u(bs, width_for(4))}


def _killed_by(bs):  # 0x08075b70
    f = {}
    f["attacker_id"] = _u(bs, 8)          # this+0xc: killer (OCR kill feed + score counters agree)
    f["victim_id"] = _u(bs, 8)            # this+0xd
    f["has_killer"] = _b(bs)              # this+0xe: fillKilledByData sets 1 only if a killer Player exists;
                                          # otherwise attacker_id is 0 and meaningless (57/57 in the samples)
    f["weapon_object_id"] = _u(bs, 16)    # this+0x10
    f["weapon_template_id"] = _u(bs, 32)  # this+0x18
    f["vehicle_template_id"] = _u(bs, 32)  # this+0x14
    f["damage_type"] = _u(bs, 8)          # this+0x28
    f["position"] = read_compressed_vector(bs)  # this+0x1c (origin=bs+0x54, scale=1000)
    return f


def _change_squad_name(bs):
    f = {"team": _u(bs, 8), "squad_id": _u(bs, 8), "player_id": _u(bs, 8)}
    f["name"] = _str8(bs)
    return f


def _set_private_squad(bs):
    return {"team": _u(bs, 8), "squad_id": _u(bs, 8), "private": _b(bs)}


def _issue_squad_order(bs):
    # IssueSquadOrderEvent::executeClient 0x08074a20 copies the fields into a SquadOrder and calls, by ``kind``,
    # ClientSquadManager::issueSquadOrder (0) / issueCommanderOrder (1) / issueRequest (2).
    f = {"team": _u(bs, 8), "squad_id": _u(bs, 8), "order": _u(bs, 8)}
    if _b(bs):
        f["target_object_id"] = _u(bs, 16)
    else:
        f["target_object_id"] = 0
        f["matrix"] = [_f32(bs) for _ in range(9)]
    f["kind"] = _u(bs, 8)
    f["flag"] = _b(bs)              # last member of the SquadOrder struct (no name in the binary)
    return f


def _invite(bs):
    return {"player_id": _u(bs, 8), "target_id": _u(bs, 8), "squad_id": _u(bs, 8),
            "flag": _b(bs)}


def _rank(bs):
    return {"kind": _u(bs, width_for(2)), "rank": _u(bs, width_for(0x20)) - 1,
            "value": _u(bs, 32), "player_id": _u(bs, 8)}


def _set_accept_order(bs):
    # SetAcceptOrderEvent::executeClient 0x0807a670 -> ClientSquadManager::setIsAccepted(team, squad, accepted, OrderType, SquadOrderType)
    return {"team": _u(bs, 8), "squad_id": _u(bs, 8), "accepted": _b(bs),
            "order_type": _u(bs, 8), "squad_order_type": _u(bs, 8)}


def _spotted(bs):
    return {"object_id": _u(bs, 16), "spotter_object_id": _u(bs, 16),
            "value_14": _u(bs, 32), "value_18": _u(bs, 32), "player_id": _u(bs, 8),
            "value_1c": _u(bs, 32), "value_20": _u(bs, 32)}


def _artillery(bs):
    # ArtilleryEvent::executeClient 0x08069890 accepts only mode 2 (server -> client; mode 1 is the client's request): the commander of
    # ``team`` (SquadManager::getCommander) is made the owner of artillery object ``object_id``, ``tick`` is stored in it at +0x1c4
    # (in every sample it equals the event's own tick +-1).
    f = {"mode": _u(bs, 2), "team": _u(bs, 32)}
    if f["mode"] == 1:
        f["value_c"] = _u(bs, 32)
        f["value_10"] = _u(bs, 32)
    elif f["mode"] == 2:
        f["object_id"] = _u(bs, 16)
        f["tick"] = _u(bs, 32)
    return f


def _create_kit(bs):
    # CreateKitEvent 0x0806d750; the server fills it in GameServer::createObjectOnAllClients with ``Kit::getCreationIndex()`` (+0x20,
    # the "kid id" of the client's failure message) and the kit member at +0x174 (+0x24; -1 = none).
    return {"template_id": _u(bs, 32), "object_id": _u(bs, 16), "position": _vec3(bs),
            "kit_id": _u(bs, 4), "kit_state": _u(bs, 4) - 1}


def _sticky_projectile(bs):
    # StickyProjectileEvent::executeClient 0x0807cca0: the projectile sticks to the target's child number ``child_index`` (a
    # rotational bundle found by ``findChildTypeIndex``) of the object ``net_id_count`` steps from ``target_object_id``
    # (``getObjectFromNetIdCount``); ``player_id`` is the shooter (compared with the local player).
    f = {"projectile_id": _u(bs, 16), "target_object_id": _u(bs, 16)}
    if f["target_object_id"]:
        f["net_id_count"] = _u(bs, 8)
        f["child_index"] = _u(bs, 8)
    f["player_id"] = _u(bs, 8)
    rows = {}
    for offset in (0x2c, 0xc, 0x1c, 0x3c):        # wire order; Mat4 rows at +0xc/+0x1c/+0x2c/+0x3c
        rows[offset] = _vec3(bs)
    f["matrix"] = [rows[0xc], rows[0x1c], rows[0x2c], rows[0x3c]]
    return f


def _ambient_effect_area(bs):
    # AmbientEffectAreaEvent::executeClient 0x08069470: AmbientEffectArea::playEffect(position, effect_index, object)
    return {"area_id": _u(bs, 16), "effect_index": _u(bs, 8), "object_id": _u(bs, 16),
            "vec": _vec3(bs)}


def _voip_on_off(bs):
    return {"player_id": _u(bs, 8), "on": _b(bs)}


def _commander_cam(bs):
    return {"position": _vec3(bs)}


def _supply_drop(bs):
    return {"flag": _u(bs, 32), "x": _f32(bs), "z": _f32(bs)}


def _voip_player_mute(bs):
    return {"mute": _b(bs), "player_id": _u(bs, 8), "target_id": _u(bs, 8)}


def _vote(bs):
    # VoteEvent::deSerialize 0x08081c00 reads +0x20, +0xc, +0x10, +0x20, +0x11, +0x12, +0x21, +0x14, +0x18, +0x1c
    # (the first +0x20 read is overwritten by the fourth). Meaning from ServerVoteManager::updateClientState.
    _u(bs, 8)                              # +0x20, discarded
    f = {"option": _u(bs, 8),              # +0xc  yes/no choice (casting) or participation flag
         "yes_votes": _u(bs, 8),           # +0x10
         "item": _u(bs, 8)}                # +0x20 voted item: player id (kick/commander) or map index, 0xff none
    f["no_votes"] = _u(bs, 8)              # +0x11
    f["votes_needed"] = _u(bs, 8)          # +0x12
    f["caster"] = _u(bs, 8)                # +0x21 player id who issued the vote, 0xff none
    f["status"] = _u(bs, 8)                # +0x14 0 state update, 4 commander state, 7 not enough players, 8/9 client requests
    f["vote_type"] = _u(bs, 8)             # +0x18 Vote::VoteType: 1 map, 2 kick player, 3 commander
    f["time_remaining"] = _f32(bs)         # +0x1c seconds
    return f


def _toggle_free_camera(bs):
    return {}


def _medal(bs):
    return {"award_id": _u(bs, 32), "player_id": _u(bs, 8), "level": _u(bs, 4)}


def _unlock(bs):
    f = {"kind": _u(bs, width_for(2)), "player_id": _u(bs, 8)}
    f["unlocks"] = [_u(bs, 4) for _ in range(14)]
    return f


def _missile_init(bs):
    # MissileInitEvent::executeClient 0x08076dc0: the projectile ``object_id`` is bound to the weapon of ``player_id`` whose
    # weapon slot (IWeaponObject vfunc 0x178) equals ``weapon_slot``; ``from_soldier`` picks the control object it searches:
    # False = Player::getVehicle (slots 0-3 in every sample), True = Player::getDefaultVehicle, the soldier (slots 4-5).
    return {"object_id": _u(bs, 16), "player_id": _u(bs, 8), "weapon_slot": _u(bs, 4),
            "from_soldier": _b(bs)}


def _uav(bs):
    return {"x": _f32(bs), "z": _f32(bs), "team": _u(bs, 8), "flag": _b(bs)}


def _content_check(bs):
    return {"hash_a": _raw(bs, 16).hex(), "hash_b": _raw(bs, 16).hex(),
            "hash_c": _raw(bs, 16).hex()}


def _target_direction(bs):
    f = {"object_id": _u(bs, 16), "player_id": _u(bs, 8)}
    f["values"] = [_f32(bs) for _ in range(6)]
    return f


def _end_of_round(bs):
    # EndOfRoundEvent ctor 0x08070920 / executeClient 0x08070b70: +0xc is the first constructor argument (winner),
    # +0x10 / +0x14 are passed to ScoreManager vtable +0x1c / +0x20 (per-team final values). No sample has one yet.
    return {"winner": _u(bs, 32), "team1_value": _u(bs, 32), "team2_value": _u(bs, 32)}


def _python_command(bs):
    f = {"command": _u(bs, 32), "player_id": _u(bs, 8)}
    n = _u(bs, 4)
    f["args"] = [_u(bs, 32) for _ in range(n)]
    return f


def _request(bs):
    return {"player_id": _u(bs, 8), "target_id": _u(bs, 8), "kind": _u(bs, width_for(4))}


def _drop_vehicle(bs):
    return {"x": _f32(bs), "z": _f32(bs), "team": _u(bs, 8), "flag": _b(bs)}


def _voip_session(bs):
    return {"session": _u(bs, 16)}


def _kick_ban(bs):
    return {"player_id": _u(bs, 8), "ban": _b(bs), "reason": _u(bs, 8)}


def _begin_round(bs):
    # BeginRoundEvent::executeClient 0x0806a1f0 (client only, not on the server): +0xc -> GameLogic::setBeginRoundState,
    # +0x10 -> GameLogic::setNextStateChangeAtTick (vtable slots read with the +8 of the ABI header, checked against
    # isServer at 0x13c). It is NOT the game status of the PostRemote events. ``next_state_change_tick`` is the tick of the
    # scheduled end of the round (round start + time limit: 151 + 72000 on a 40 minute server) or 0 without a time limit.
    # The BeginRoundState names are not in the binaries' symbols: 3 at the start of every server round, 1 in manual recordings.
    return {"begin_round_state": _u(bs, 32), "next_state_change_tick": _u(bs, 32)}


def _create_spawn_group(bs):  # 0x0806f2c0
    # SpawnManager::createSpawnGroupOnClients 0x08113010 fills the event from the SpawnGroup: active (getActive), the flag at +0x6e
    # (only_for_ai: read by getActive(false) beside onlyForHuman at +0x6f), the flag at +0x74 (set by addSpawnPoint: has_spawn_points)
    # and the minimap position (``getUnsignedWorldPosition``: map_x / map_z bytes, world = size * byte / 255 - size / 2).
    return {"spawn_group_id": _u(bs, 8), "team": _u(bs, 4), "active": _b(bs),
            "only_for_ai": _b(bs), "has_spawn_points": _b(bs), "map_x": _u(bs, 8),
            "map_z": _u(bs, 8), "object_id": _u(bs, 16)}


def _remove_spawn_group(bs):
    return {"spawn_group_id": _u(bs, 8), "object_id": _u(bs, 16)}


def _update_trigger(bs):
    # UpdateTriggerEvent::executeClient 0x08080ba0 is empty (returns 1): the client ignores every field. Never seen in a sample.
    return {"template_id": _u(bs, 32), "object_id": _u(bs, 16), "position": _vec3(bs),
            "rotation": _vec3(bs), "unk_30": _u(bs, 8), "unk_2c": _u(bs, 8)}


def _gh_container_create(bs):
    # GrapplingHookContainerCreateEvent::executeClient 0x08071a80 -> GrapplingHookRope::initContainer(container, soldier, int, float)
    # (never seen in a sample; the 8-bit width of ``segment`` is unverified)
    return {"player_id": _u(bs, 8), "object_id": _u(bs, 16), "segment": _u(bs, 8),
            "value": _f32(bs)}


def _gh_container_update(bs):
    # GrapplingHookContainerUpdateEvent::executeClient 0x08072410: the container sits ``fraction`` (0..1) of the way along rope
    # segment ``segment``; ``value`` is stored at container+0x408 (never seen in a sample)
    return {"player_id": _u(bs, 8), "segment": _u(bs, 8), "fraction": _f32(bs), "value": _f32(bs)}


def _gh_container_detach(bs):
    return {"player_id": _u(bs, 8), "position": _vec3(bs)}


def _gh_create(bs):
    return {"object_id": _u(bs, 16), "player_id": _u(bs, 8), "value_14": _u(bs, 32),
            "position": _vec3(bs), "direction": _vec3(bs)}


def _gh_update(bs):
    # GrapplingHookUpdateEvent::executeClient 0x08073170: rope point ``point_index`` (record of 0x2c bytes) gets position,
    # velocity and ``flag`` (record+0x29); never seen in a sample
    return {"object_id": _u(bs, 16), "point_index": _u(bs, 8),
            "position": read_compressed_vector(bs), "velocity": read_compressed_vector(bs),
            "flag": _b(bs)}


def _player_tear_gassed(bs):
    return {"player_id": _u(bs, 8), "value_10": _f32(bs), "value_14": _f32(bs),
            "value_18": _f32(bs)}


def _set_night_vision(bs):
    return {"player_id": _u(bs, 8), "on": _b(bs)}


def _four_u8(bs):
    return {"value_d": _u(bs, 8), "value_c": _u(bs, 8), "value_f": _u(bs, 8),
            "value_e": _u(bs, 8)}


def _verify_player_team(bs):
    return {"value_c": _u(bs, 8), "value_d": _u(bs, 8), "value_e": _u(bs, 8),
            "value_f": _u(bs, 8)}


_READERS: Dict[int, Callable[[BitStream], dict]] = {
    1: _challenge, 2: _challenge_response, 3: _connection_type, 4: _data_block,
    5: _create_player, 6: _create_object, 7: _destroy_object, 8: _destroy_player,
    9: _enter_vehicle, 10: _exit_vehicle, 11: _post_remote, 12: _change_player_name,
    13: _handle_drop, 14: _handle_pickup, 15: _string_block, 16: _three_u8,
    17: _leave_squad, 19: _commander, 20: _radio_message, 21: _killed_by,
    22: _change_squad_name, 23: _set_private_squad, 24: _issue_squad_order,
    25: _invite, 26: _rank, 27: _set_accept_order,
    28: _three_u8,  # SetSquadLeaderEvent reuses JoinSquadEvent::deSerialize
    29: _spotted, 30: _artillery, 31: _create_kit, 32: _sticky_projectile,
    34: _ambient_effect_area, 35: _voip_on_off, 36: _commander_cam, 37: _supply_drop,
    38: _voip_player_mute, 39: _vote, 40: _toggle_free_camera, 41: _medal,
    42: _unlock, 43: _missile_init, 45: _uav, 46: _content_check,
    47: _target_direction, 48: _end_of_round, 49: _python_command, 50: _request,
    51: _drop_vehicle, 54: _voip_session, 55: _kick_ban, 56: _begin_round,
    57: _create_spawn_group, 58: _remove_spawn_group, 59: _update_trigger,
    60: _gh_container_create, 61: _gh_container_update, 62: _gh_container_detach,
    63: _gh_create, 64: _gh_update, 65: _player_tear_gassed, 66: _set_night_vision,
    68: _verify_player_team, 69: _four_u8,
}


def register_event(eid: int, name: str, reader: Callable[[BitStream], Dict[str, object]]) -> None:
    """Teach the parser a new event kind (or replace a layout): ``reader`` consumes the body after the id and returns its fields.

    This is the one place a new event is added: it keeps :data:`EVENT_NAMES` and the reader table in step.
    """
    EVENT_NAMES[eid] = name
    _READERS[eid] = reader


def read_event(bs: BitStream, eid_bits: int = EID_BITS) -> GameEvent:
    """Deserialize one event (id + body) from ``bs``."""
    start = bs.bit_pos
    eid = bs.read_bits(eid_bits)
    reader = _READERS.get(eid)
    if reader is None:
        raise EventReadError(f"unregistered event id {eid} at bit {start}")
    fields = reader(bs)
    if bs.overrun:
        raise EventReadError(f"event {EVENT_NAMES[eid]} overran the packet at bit {start}")
    return GameEvent(eid, EVENT_NAMES[eid], fields, start, bs.bit_pos)
