"""Single-pass replay model built from the decoded packet stream.

Everything here is read from the demo itself: server/map-rotation data blocks,
created/destroyed objects with their exact template, control-point state from
ghost updates, and game events. The only external data is the bundled
template table (``assets/templates.json.gz``), which maps template ids to names.
"""

from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .events import GameEvent
from .models import Demo
from .networkables import ControlPointUpdate, decode_control_point, decode_player, decode_score_manager
from .packet import GHOST_REMOVE, GHOST_UPDATE, PacketError, parse_packet
from .serverinfo import decode_map_info, decode_server_info
from .templatedb import TemplateDB, TemplateInfo

Vec3 = Tuple[float, float, float]


@dataclass
class GameObject:
    object_id: int
    template_id: int
    team: int
    position: Optional[Vec3]
    rotation: Optional[Vec3]
    created_tick: int
    destroyed_tick: Optional[int] = None
    template: Optional[TemplateInfo] = None
    snapshot: bool = False    # sent in the join snapshot (current, not spawn, transform)
    #: EnterVehicleEvent records onto this object: (tick, player_id, is_spawn). A Soldier object is entered by its player
    #: in the tick it is created (flag True), which is the only player <-> soldier link in the stream.
    enters: List[Tuple[int, int, bool]] = field(default_factory=list)

    @property
    def owner_id(self) -> Optional[int]:
        """Player id that spawned into this Soldier object (first enter with flag True), else None."""
        if self.template is None or self.template.cls != "Soldier":
            return None
        for _, player_id, flag in self.enters:
            if flag:
                return player_id
        return None


@dataclass
class Player:
    """One player slot occupancy: CreatePlayer ... DestroyPlayer (or end of the demo).

    ``team`` / ``squad_id`` / ``kit`` / counters are decoded from the Player ghost
    (``Player::setNetUpdate``); ``*_history`` lists hold ``(tick, value)`` changes.
    The server never sends a network address, a CD-key hash or a profile id for a
    player: the only identity fields on the wire are ``name`` and ``player_id``.
    """

    player_id: int
    ghost_id: int
    name: str
    is_ai: bool
    is_remote: bool
    join_tick: int
    leave_tick: Optional[int] = None
    create_team: Optional[int] = None          # CreatePlayerEvent team (3 bits)
    names: List[Tuple[int, str]] = field(default_factory=list)
    team_history: List[Tuple[int, int]] = field(default_factory=list)
    squad_history: List[Tuple[int, int]] = field(default_factory=list)
    kit_history: List[Tuple[int, int]] = field(default_factory=list)
    rank_history: List[Tuple[int, int]] = field(default_factory=list)    # (tick, PlayerScoreData rank): the rank icon of the scoreboard
    score_history: List[Tuple[int, int]] = field(default_factory=list)   # (tick, PlayerScoreData score)
    #: (tick, kills, deaths, teamwork score, team kills) of PlayerScoreData each time one of them changes (the scoreboard's columns)
    stats_history: List[Tuple[int, int, int, int, int]] = field(default_factory=list)
    #: (tick, mask) changes of the squad invitations of this player: bit n set = invited to squad n (Player::getIsInvitedToSquad)
    invite_history: List[Tuple[int, int]] = field(default_factory=list)
    state: Dict[str, object] = field(default_factory=dict)     # latest ghost fields
    first_state: Dict[str, object] = field(default_factory=dict)  # values in the join snapshot
    kicked: Optional[Tuple[int, bool]] = None   # (tick, banned)

    @property
    def team(self) -> Optional[int]:
        return self.team_history[-1][1] if self.team_history else self.create_team

    def team_at(self, tick: int) -> Optional[int]:
        team = self.create_team
        for t, value in self.team_history:
            if t > tick:
                break
            team = value
        return team


@dataclass
class ControlPointState:
    object_id: int
    template_id: int
    position: Optional[Vec3]
    team: Optional[int] = None
    flag_team: Optional[int] = None
    allow_capture: Tuple[Optional[bool], Optional[bool]] = (None, None)
    initial_team: Optional[int] = None
    history: List[Tuple[int, int]] = field(default_factory=list)  # (tick, team)
    template: Optional[TemplateInfo] = None


@dataclass
class SpawnSite:
    """A vehicle spawner reconstructed from the demo.

    ObjectSpawners are server-only and never cross the wire, but each vehicle
    they create does (``CreateObjectEvent``). A vehicle created *during* the
    recording carries the spawner's exact ``absolutePosition``/``rotation``
    (verified to 3 decimals against ``GamePlayObjects.con`` on every respawn
    in ``samples/zxc.bf2demo``), so fresh creations sharing a transform are one
    spawner. Objects in the join snapshot are sent with their *current*
    transform: exact only for ``hasMobilePhysics 0`` templates (emplacements,
    artillery, static structures); mobile vehicles may have settled or moved.
    """

    position: Vec3
    rotation: Vec3
    exact: bool                                              # from a fresh creation
    templates: Dict[str, int] = field(default_factory=dict)  # name -> fresh spawns
    snapshot_templates: List[str] = field(default_factory=list)
    #: every creation seen at this site: (tick, template name, object team field, from snapshot)
    observations: List[Tuple[int, str, int, bool]] = field(default_factory=list)
    first_tick: int = 0
    nearest_cp: Optional[ControlPointState] = None
    nearest_cp_distance: Optional[float] = None

    @property
    def confirmed(self) -> bool:
        """Exact transform seen twice, or a static (non-mobile) object."""
        return self.exact and (sum(self.templates.values()) + len(self.snapshot_templates) > 1
                               or bool(self.snapshot_templates))


@dataclass
class KitSpawn:
    """A soldier spawn (``CreateKitEvent``): the exact spawn position.

    For a SpawnPoint spawn this is ``absolutePosition + spawnPositionOffset``.
    """

    tick: int
    position: Vec3
    object_id: int
    kit_template_id: int
    kit_id: int            # Kit::getCreationIndex() on the server


@dataclass
class MapEntry:
    level: str
    mode: str
    size: int


@dataclass
class Replay:
    demo: Demo
    map_rotation: List[MapEntry] = field(default_factory=list)
    current_map: Optional[int] = None
    game_mode: Optional[str] = None
    server_name: Optional[str] = None
    #: the server settings of the join DataBlock (kind 0), see :mod:`bf2demo.serverinfo`; None when the block is missing
    server_info: Optional[Dict[str, object]] = None
    #: the current map block (DataBlock kind 2: mode, level, max players, commander), see :func:`bf2demo.serverinfo.decode_map_info`
    map_info: Optional[Dict[str, object]] = None
    events: List[Tuple[int, GameEvent]] = field(default_factory=list)
    objects: Dict[int, GameObject] = field(default_factory=dict)
    object_history: List[GameObject] = field(default_factory=list)
    #: seat changes in stream order: ``(tick, player_id, object_id)``; ``object_id`` is the vehicle / parachute / soldier object
    #: the player entered (``EnterVehicle``) or None when the player left the vehicle (``ExitVehicle``, which names no object)
    seat_events: List[Tuple[int, int, Optional[int]]] = field(default_factory=list)
    control_points: Dict[int, ControlPointState] = field(default_factory=dict)
    spawn_sites: List[SpawnSite] = field(default_factory=list)
    kit_spawns: List[KitSpawn] = field(default_factory=list)
    #: team -> [(tick, tickets)] from the ScoreManager ghost (ghost id: ``score_manager_id``)
    tickets: Dict[int, List[Tuple[int, int]]] = field(default_factory=dict)
    score_manager_id: Optional[int] = None
    players: Dict[int, Player] = field(default_factory=dict)       # player_id -> current occupant
    player_history: List[Player] = field(default_factory=list)     # every occupancy in order
    packet_errors: List[Tuple[int, str]] = field(default_factory=list)
    #: recording times of every demo merged into this replay by :func:`bf2demo.merge.merge_replays` (empty for a single demo)
    merged_from: List[str] = field(default_factory=list)
    templates: Optional[TemplateDB] = None
    first_tick: Optional[int] = None
    last_tick: Optional[int] = None
    _index: Optional[Dict[int, List[GameObject]]] = field(default=None, repr=False)
    _sorted_ids: Optional[List[int]] = field(default=None, repr=False)

    def _build_index(self) -> None:
        index: Dict[int, List[GameObject]] = {}
        for obj in self.object_history:
            index.setdefault(obj.object_id, []).append(obj)
        self._index = index
        self._sorted_ids = sorted(index)

    def object_at(self, object_id: int, tick: int) -> Optional[GameObject]:
        """The object instance with this id alive at ``tick`` (ids are reused after DestroyObject)."""
        if self._index is None:
            self._build_index()
        for obj in reversed(self._index.get(object_id, [])):
            if obj.created_tick <= tick and (obj.destroyed_tick is None or obj.destroyed_tick >= tick):
                return obj
        return None

    def nested_owner(self, ghost_id: int, tick: int) -> Optional[Tuple[GameObject, int]]:
        """``(vehicle root, nested PlayerControlObject index)`` for a ghost id in the id block after a vehicle root.

        The ids ``root + 1 + index`` belong to the nested PlayerControlObjects (turret and passenger seats) of the root.
        """
        if self._index is None:
            self._build_index()
        position = bisect.bisect_right(self._sorted_ids, ghost_id) - 1
        if position < 0:
            return None
        root = self.object_at(self._sorted_ids[position], tick)
        if root is None or root.template is None or not root.template.pco_children:
            return None
        index = ghost_id - root.object_id - 1
        return (root, index) if 0 <= index < len(root.template.pco_children) else None

    @property
    def level(self) -> str:
        return self.demo.header.map_name.strip().lower()

    @property
    def map_size(self) -> Optional[int]:
        if self.current_map is not None and self.current_map < len(self.map_rotation):
            entry = self.map_rotation[self.current_map]
            if entry.level.lower() == self.level:
                return entry.size
        for entry in self.map_rotation:
            if entry.level.lower() == self.level and (not self.game_mode or entry.mode == self.game_mode):
                return entry.size
        return None


# --------------------------------------------------------------------------- #
# Data blocks (DataBlockEvent kind/length header followed by chunks)
# --------------------------------------------------------------------------- #

def _str16(buf: bytes, off: int) -> Tuple[str, int]:
    n = struct.unpack_from("<H", buf, off)[0]
    return buf[off + 2: off + 2 + n].decode("latin1"), off + 2 + n


def _parse_map_rotation(buf: bytes) -> Tuple[List[MapEntry], int]:
    """``count(u16) current(u16)`` then ``count`` x ``str16 level, str16 mode, u16 size``."""
    count, current = struct.unpack_from("<HH", buf, 0)
    off, out = 4, []
    for _ in range(count):
        level, off = _str16(buf, off)
        mode, off = _str16(buf, off)
        size = struct.unpack_from("<H", buf, off)[0]
        off += 2
        out.append(MapEntry(level, mode, size))
    return out, current


def _apply_data_block(replay: Replay, kind: int, buf: bytes) -> None:
    try:
        if kind == 0:
            replay.server_name, _ = _str16(buf, 0)
            replay.server_info = decode_server_info(buf)
        elif kind == 5:
            replay.map_rotation, replay.current_map = _parse_map_rotation(buf)
        elif kind == 2:
            replay.game_mode, _ = _str16(buf, 0)
            replay.map_info = decode_map_info(buf)
    except (struct.error, IndexError):
        pass


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def _maybe_score_manager(replay: Replay, tick: int, data: bytes, ghost) -> None:
    """A ghost that is neither an object nor a player and whose first record is a full ScoreManager state."""
    if replay.score_manager_id is None:
        if ghost.bit_length < 32:
            return
        update = decode_score_manager(data, ghost.bit_start)
        # the full state (every bit set) is longer than the 32 numbers: it carries 78 more bits that are not decoded
        if update.mask != 0xFFFFFFFF or ghost.bit_length < update.bits:
            return
        replay.score_manager_id = ghost.ghost_id
        for team, tickets in update.tickets.items():
            replay.tickets.setdefault(team, []).append((tick, tickets))
        return
    elif ghost.ghost_id != replay.score_manager_id:
        return
    update = decode_score_manager(data, ghost.bit_start)
    if update.bits != ghost.bit_length:
        return
    for team, tickets in update.tickets.items():
        history = replay.tickets.setdefault(team, [])
        if not history or history[-1][1] != tickets:
            history.append((tick, tickets))


def _apply_player_update(player: Player, tick: int, data: bytes, ghost) -> None:
    update = decode_player(data, ghost.bit_start)
    if update.bits != ghost.bit_length:
        return                         # never apply a partially understood record
    for key, value in update.fields.items():
        if key == "weapon_slots":
            continue
        if key not in player.first_state:
            player.first_state[key] = value
        player.state[key] = value
    f = update.fields
    if "score" in f and (not player.score_history or player.score_history[-1][1] != f["score"]):
        player.score_history.append((tick, f["score"]))
    if any(key in f for key in ("kills", "deaths", "teamwork", "teamkills")):
        row = tuple(int(player.state.get(key, 0) or 0) for key in ("kills", "deaths", "teamwork", "teamkills"))
        if not player.stats_history or player.stats_history[-1][1:] != row:
            player.stats_history.append((tick,) + row)
    for key, hist in (("team", player.team_history), ("squad_id", player.squad_history),
                      ("kit", player.kit_history), ("rank", player.rank_history), ("squad_invite_mask", player.invite_history)):
        if key in f and (not hist or hist[-1][1] != f[key]):
            hist.append((tick, f[key]))


def build_replay(demo: Demo) -> Replay:
    replay = Replay(demo)
    block: Optional[List] = None      # [kind, length, bytearray]
    cp_candidates: Dict[int, List[Tuple[int, ControlPointUpdate]]] = {}
    ghost_players: Dict[int, Player] = {}
    not_control_point: set = set()

    for packet in demo.packets:
        if not packet.data:
            continue
        try:
            pkt = parse_packet(packet.data)
        except PacketError as exc:
            replay.packet_errors.append((packet.index, str(exc)))
            continue
        tick = packet.tick
        if tick >= 0:
            replay.first_tick = tick if replay.first_tick is None else replay.first_tick
            replay.last_tick = tick

        for ev in pkt.events:
            replay.events.append((tick, ev))
            if ev.name == "CreatePlayer":
                player = Player(ev["player_id"], ev["ghost_id"], ev["name"], ev["is_ai"],
                                ev["is_remote"], tick, create_team=ev["team"])
                replay.players[player.player_id] = player
                replay.player_history.append(player)
                ghost_players[player.ghost_id] = player
            elif ev.name == "DestroyPlayer":
                player = replay.players.pop(ev["player_id"], None)
                if player is not None:
                    player.leave_tick = tick
            elif ev.name == "ChangePlayerName":
                player = replay.players.get(ev["player_id"])
                if player is not None:
                    player.names.append((tick, ev["name"]))
                    player.name = ev["name"]
            elif ev.name == "KickBan":
                player = replay.players.get(ev["player_id"])
                if player is not None:
                    player.kicked = (tick, bool(ev["ban"]))
            if ev.name == "DataBlock":
                if ev["is_header"]:
                    block = [ev["kind"], ev["length"], bytearray()]
                elif block is not None:
                    block[2] += ev["data"]
                    if len(block[2]) >= block[1]:
                        _apply_data_block(replay, block[0], bytes(block[2]))
                        block = None
            elif ev.name == "CreateObject":
                obj = GameObject(ev["object_id"], ev["template_id"], ev["team"],
                                 ev["position"], ev["rotation"], tick)
                replay.objects[obj.object_id] = obj
                replay.object_history.append(obj)
            elif ev.name == "EnterVehicle":
                target = replay.objects.get(ev["object_id"])
                if target is not None:
                    target.enters.append((tick, ev["player_id"], ev["is_spawn"]))
                replay.seat_events.append((tick, ev["player_id"], ev["object_id"]))
            elif ev.name == "ExitVehicle":
                replay.seat_events.append((tick, ev["player_id"], None))
            elif ev.name == "CreateKit":
                replay.kit_spawns.append(KitSpawn(tick, ev["position"], ev["object_id"],
                                                  ev["template_id"], ev["kit_id"]))
            elif ev.name == "DestroyObject":
                obj = replay.objects.pop(ev["object_id"], None)
                if obj is not None:
                    obj.destroyed_tick = tick

        for ghost in pkt.ghosts:
            if ghost.action != GHOST_UPDATE:
                continue
            if ghost.ghost_id in ghost_players:
                _apply_player_update(ghost_players[ghost.ghost_id], tick, packet.data, ghost)
                continue
            if ghost.ghost_id not in replay.objects:
                _maybe_score_manager(replay, tick, packet.data, ghost)
                continue
            # Control points are identified by decoding: a ControlPointNetworkable
            # update consumes its record exactly. Candidates are level templates.
            # An object is a control point only if EVERY update decodes exactly, so the first record that does not
            # disproves it for good and its remaining updates are not decoded again (most ghosts are soldiers and vehicles).
            if ghost.ghost_id in not_control_point:
                continue
            update = decode_control_point(packet.data, ghost.bit_start)
            if update.bits == ghost.bit_length:
                cp_candidates.setdefault(ghost.ghost_id, []).append((tick, update))
            else:
                cp_candidates.setdefault(ghost.ghost_id, []).append((tick, None))
                not_control_point.add(ghost.ghost_id)

    if replay.object_history:
        join_tick = replay.object_history[0].created_tick
        for obj in replay.object_history:
            obj.snapshot = obj.created_tick == join_tick
    db = TemplateDB(replay.level)
    replay.templates = db
    proven = _prove_control_points(replay, cp_candidates)
    db.select_layer([obj.template_id for obj, _ in proven.values()],
                    replay.game_mode, replay.map_size)
    for obj in replay.object_history:
        obj.template = db.lookup(obj.template_id)
    _build_control_points(replay, proven)
    _build_spawn_sites(replay)
    return replay


def _dist(a: Vec3, b: Vec3) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _transform_key(pos: Vec3, rot: Optional[Vec3]):
    rot = rot or (0.0, 0.0, 0.0)
    yaw = round(rot[0], 3) % 360.0
    return tuple(round(c, 3) for c in pos) + (round(yaw, 3),)


#: A snapshot vehicle is attributed to a fresh spawner of the same template
#: when it has not moved further than this from it.
SNAPSHOT_MATCH_RADIUS = 5.0


def _build_spawn_sites(replay: Replay) -> None:
    vehicles = [o for o in replay.object_history
                if o.position is not None and o.template is not None and o.template.is_vehicle]
    sites: Dict[tuple, SpawnSite] = {}

    def fresh(obj):
        key = _transform_key(obj.position, obj.rotation)
        site = sites.get(key)
        if site is None:
            site = sites[key] = SpawnSite(obj.position, obj.rotation or (0.0, 0.0, 0.0), True,
                                          first_tick=obj.created_tick)
        return site

    for obj in vehicles:
        if not obj.snapshot:
            site = fresh(obj)
            site.templates[obj.template.name] = site.templates.get(obj.template.name, 0) + 1
            site.observations.append((obj.created_tick, obj.template.name, obj.team, False))
        elif obj.template.mobile is False:
            # hasMobilePhysics 0: the snapshot transform is the spawn transform.
            site = fresh(obj)
            site.snapshot_templates.append(obj.template.name)
            site.observations.append((obj.created_tick, obj.template.name, obj.team, True))
    ordered = list(sites.values())
    for obj in vehicles:
        if not obj.snapshot or obj.template.mobile is False:
            continue
        same = [s for s in ordered if s.exact and obj.template.name in s.templates
                and _dist(s.position, obj.position) <= SNAPSHOT_MATCH_RADIUS]
        if same:
            site = min(same, key=lambda s: _dist(s.position, obj.position))
            site.snapshot_templates.append(obj.template.name)
            site.observations.append((obj.created_tick, obj.template.name, obj.team, True))
            continue
        site = SpawnSite(obj.position, obj.rotation or (0.0, 0.0, 0.0), False,
                         first_tick=obj.created_tick)
        site.snapshot_templates.append(obj.template.name)
        site.observations.append((obj.created_tick, obj.template.name, obj.team, True))
        ordered.append(site)
    cps = [cp for cp in replay.control_points.values() if cp.position]
    for site in ordered:
        if cps:
            cp = min(cps, key=lambda c: _dist(c.position, site.position))
            site.nearest_cp, site.nearest_cp_distance = cp, _dist(cp.position, site.position)
    ordered.sort(key=lambda s: (s.nearest_cp.object_id if s.nearest_cp else 0, not s.exact,
                                s.first_tick))
    replay.spawn_sites = ordered


def _prove_control_points(replay: Replay, candidates) -> Dict[int, tuple]:
    """Objects whose every ghost update decodes exactly as a control point."""
    proven = {}
    global_count = replay.templates.global_count
    for object_id, updates in candidates.items():
        obj = next((o for o in reversed(replay.object_history) if o.object_id == object_id), None)
        if obj is None or obj.template_id < global_count:
            continue
        if updates and all(u is not None for _, u in updates):
            proven[object_id] = (obj, updates)
    return proven


def _build_control_points(replay: Replay, proven) -> None:
    db = replay.templates
    for object_id, (obj, updates) in sorted(proven.items()):
        obj.template = db.lookup(obj.template_id)
        state = ControlPointState(object_id, obj.template_id, obj.position, template=obj.template)
        for tick, update in updates:
            f = update.fields
            if "team" in f:
                if state.initial_team is None:
                    state.initial_team = f["team"]
                if f["team"] != state.team:
                    state.history.append((tick, f["team"]))
                state.team = f["team"]
            if "flag_team" in f:
                state.flag_team = f["flag_team"]
            a1, a2 = state.allow_capture
            state.allow_capture = (f.get("allow_capture_team1", a1), f.get("allow_capture_team2", a2))
        replay.control_points[object_id] = state
