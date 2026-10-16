"""Catalogue of everything a ``.bf2demo`` can contain, and what it can never contain.

One table (:data:`CATALOG`) describes every kind of data: where it comes from on the wire, how trustworthy it is, how to get it out
with this package, and which events carry it. :func:`inventory` counts, for one demo, how much of each kind is actually present;
``python -m bf2demo DEMO --inventory`` prints it, ``scripts/build_data_doc.py`` renders the whole catalogue (plus the events seen in
all samples) as ``DATA.md``. A new data kind is one new :class:`Category` entry.

``exactness``: *exact* = the value the server computed; *snapshot* = the value at the moment the recording began (it may have changed
since); *derived* = reconstructed by this package from exact pieces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .replay import Replay


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    source: str                              # event names / ghost classes / blocks it comes from
    exactness: str                           # "exact" | "snapshot" | "derived"
    contents: str                            # what is in it
    use: str                                 # how to read it with this package
    events: Tuple[str, ...] = ()             # event names whose count measures how much of it is present
    count: Optional[Callable[[Replay], int]] = None   # other measure (players, objects ...), in the unit ``unit``
    unit: str = ""                           # what ``count`` counts (shown next to it)
    notes: str = ""


def _objects(cls: str) -> Callable[[Replay], int]:
    return lambda r: sum(1 for o in r.object_history if o.template is not None and o.template.cls == cls)


def _classes(*names: str) -> Callable[[Replay], int]:
    return lambda r: sum(1 for o in r.object_history if o.template is not None and o.template.cls in names)


CATALOG: List[Category] = [
    Category("header", "Demo header", "file header", "exact",
             "engine version, recording time, server name, map name", "--report overview"),
    Category("settings", "Server settings", "DataBlock kind 0 (ServerInfo)", "exact",
             "name, welcome message, rounds per map, time limit, spawn time, ticket/team ratio, vehicles on/off, voting, team-kill "
             "punishment, cameras, radio spam limits, voip ports and quality, co-op bots",
             "--report settings, --export-json",
             notes="never the server IP, the admin or rcon password, or the sv.password"),
    Category("map", "Current map", "DataBlock kind 2 (MapInfo), kind 5 (MapList)", "exact",
             "mode, level, max players, commander enabled, the whole map rotation and the current position in it",
             "--report overview, --map-info"),
    Category("round", "Round schedule", "BeginRound, EndOfRound, PostRemote game status", "exact",
             "round start, scheduled end tick (time limit), game status changes, winner at the end",
             "--report overview/timeline", events=("BeginRound", "EndOfRound"),
             notes="the recorder stops when the round ends, so EndOfRound is never stored (3 of 92 two-day recordings end with a team at 5 tickets or less); the report infers the ending from the last tickets and flags"),
    Category("players", "Players", "CreatePlayer, DestroyPlayer, ChangePlayerName, KickBan, Player ghost", "exact",
             "slot id, name (and renames), bot or human, team and team changes, squad, kit, score, kills, deaths, team kills, "
             "ping, rank, medals placement counts, commander flag, connected/left times, kicks and bans",
             "--scoreboard, --report players, --export-json", events=("CreatePlayer", "DestroyPlayer", "ChangePlayerName", "KickBan"),
             count=lambda r: len(r.player_history), unit="players",
             notes="the wire carries no IP address, CD-key hash or profile id; only the name and the slot id"),
    Category("tickets", "Tickets", "ScoreManager ghost", "exact", "tickets of both teams over time", "--report teams",
             count=lambda r: sum(len(h) for h in r.tickets.values()), unit="ticket updates"),
    Category("kills", "Kills and deaths", "KilledBy, PostRemote (death, score awards)", "exact",
             "killer, victim, weapon or vehicle, assists, suicides, team kills", "--feed, --scoreboard", events=("KilledBy",)),
    Category("flags", "Control points", "CreateObject (ControlPoint), ControlPoint ghost", "exact",
             "name, exact position, owner at the start and every change of owner, capture progress, flag raised for which team",
             "--map-info, --report flags", count=_objects("ControlPoint"), unit="flags",
             notes="no capture radius, capture times or controlPointId: those are in the server's GamePlayObjects.con only"),
    Category("objects", "World objects", "CreateObject, DestroyObject, join snapshot", "snapshot",
             "every vehicle, emplacement, soldier body, projectile, destructible: template, team, position, rotation, lifetime",
             "--export-json, --tracks", events=("CreateObject", "DestroyObject"), count=lambda r: len(r.object_history), unit="objects",
             notes="exact spawn transform only for objects created during the recording; objects in the join snapshot carry "
                   "their current transform (a vehicle may have moved or settled)"),
    Category("tracks", "Movement tracks", "ghost updates of soldiers, vehicles, projectiles", "exact",
             "position and rotation samples over time, owner player, distance travelled",
             "--tracks, --export-tracks, --export-json --json-tracks", count=_classes("Soldier", "PlayerControlObject"), unit="tracked objects"),
    Category("soldier", "Soldier state", "Soldier ghost", "exact",
             "pose (stand/crouch/prone), aim angles, yaw/pitch, velocity, sprint, swimming, sky diving, weapon in hand, "
             "ladder and zipline use, ragdoll bones after death", "--export-json --json-tracks", count=_objects("Soldier"), unit="soldier bodies"),
    Category("vehicles", "Vehicle element state", "PlayerControlObject ghost bodies (turrets, rotors, wings, engines, springs)",
             "exact", "turret and gun angles, rotor and control-surface angles, engine values, landing gear, in physical units",
             "--export-parts, --export-json --json-parts", count=_objects("PlayerControlObject"), unit="vehicles/emplacements"),
    Category("occupancy", "Who sat where", "EnterVehicle, ExitVehicle", "exact",
             "player enters/leaves an object (a soldier object is entered by its player when created)", "--feed-verbose",
             events=("EnterVehicle", "ExitVehicle")),
    Category("projectiles", "Projectiles", "MissileInit, StickyProjectile, GenericProjectile ghost", "exact",
             "which weapon slot of which player fired which projectile, sticky charges and where they stuck",
             "--report weapons", events=("MissileInit", "StickyProjectile"), count=_objects("GenericProjectile"), unit="projectile objects"),
    Category("spawns", "Soldier spawns", "CreateKit, CreateSpawnGroup, RemoveSpawnGroup", "exact",
             "exact spawn position of every soldier (basis of SpawnPoint reconstruction), spawn groups and their minimap cell, "
             "which are active", "--export-con", events=("CreateKit", "CreateSpawnGroup", "RemoveSpawnGroup"),
             notes="a spawn point is only provable when two soldiers spawned at the identical position"),
    Category("kits", "Kit pickups", "HandlePickup, HandleDrop", "exact", "kit picked up or dropped, by whom, where",
             "--events", events=("HandlePickup", "HandleDrop")),
    Category("squads", "Squads and orders", "Player ghost (squad_id, squad_invite_mask), SetSquadLeader, ChangeSquadName, SetPrivateSquad, "
             "IssueSquadOrder, SetAcceptOrder, TargetDirection", "exact",
             "squad membership over time, invitations (bit n = invited by squad n), leaders, private squads, orders and who accepted",
             "--report squads, --feed",
             events=("SetSquadLeader", "ChangeSquadName", "SetPrivateSquad", "IssueSquadOrder", "SetAcceptOrder", "Invite",
                     "Spotted", "TargetDirection")),
    Category("commander", "Commander", "Commander, Artillery, PostRemote (UAVVehicleCreated/Destroyed, AddParachuteToDropVehicle), "
             "objects uav_pred / supply_crate / parachute", "exact",
             "commander changes, UAV launches and losses, supply crates and parachute drops, artillery control", "--report commander, --feed",
             events=("Commander", "Artillery")),
    Category("votes", "Votes", "Vote", "exact", "kind, caller, subject, result and time remaining", "--feed", events=("Vote",)),
    Category("awards", "Ranks, medals and unlocks", "Rank, Medal, Unlock", "exact", "rank ups, medals earned, unlock choices",
             "--events", events=("Rank", "Medal", "Unlock")),
    Category("voip", "Voice chat activity", "VoipOnOff, VoipPlayerMute, VoipSession", "exact",
             "who started and stopped talking, who muted whom (never the audio)", "--events",
             events=("VoipOnOff", "VoipPlayerMute", "VoipSession")),
    Category("radio", "Radio commands and HUD messages", "RadioMessage, PostRemote", "exact",
             "radio command messages and the HUD messages of the server", "--feed", events=("RadioMessage", "PostRemote"),
             notes="free-text chat is not among the 63 game event classes (it uses a separate message layer); StringBlock is a data block like DataBlock and is in no sample"),
    Category("static", "Networked static objects", "CreateObject (DestroyableObject)", "snapshot",
             "destructible bridges, crates, barrels, doors that the server announces", "--export-static",
             count=_objects("DestroyableObject"), unit="static objects"),
    Category("environment", "Environment", "AmbientEffectArea, SetNightVision, PlayerTearGassed", "exact",
             "smoke and gas areas, night vision, tear gas", "--events", events=("AmbientEffectArea", "SetNightVision", "PlayerTearGassed")),
    Category("hooks", "Grappling hook", "GrapplingHook* events", "exact", "rope creation, points and container position",
             "--events", events=("GrapplingHookCreate", "GrapplingHookUpdate", "GrapplingHookContainerCreate",
                                 "GrapplingHookContainerUpdate", "GrapplingHookContainerDetach")),
    Category("gamemap", "Reconstructed GamePlayObjects.con", "all of the above", "derived",
             "flags, vehicle spawners and spawn points of the recorded map as a server GamePlayObjects.con",
             "--export-con", notes="see DATA.md, 'Never in a demo' for what the file can only copy from the original map"),
]

#: What a demo can never give, with the reason (verified in the binaries unless noted).
NEVER: List[Tuple[str, str]] = [
    ("Player IP addresses, CD-key hashes, profile ids", "the server never sends them; CreatePlayer has name and slot id only"),
    ("Server IP, rcon/admin password, sv.password", "not part of the ServerInfo block; the voip address field is always 1"),
    ("CombatArea (map bounds)", "created only by the server's .con (CombatAreaManager::createCombatArea); the polygon is never sent. Only its effect is visible: each player's `time_outside_world` (Player ghost) while outside it"),
    ("controlPointId, flag radius, capture times, unableToChangeTeam", "server-side template properties, not replicated"),
    ("Vehicle spawner delays and min/max respawn times", "ObjectSpawners are server-only; only the vehicles they create cross the wire"),
    ("SpawnPoint rotation", "a soldier spawns with the point's position only (CreateKit has no rotation)"),
    ("Exact position of a vehicle that existed before the recording began",
     "the join snapshot sends the current transform; a fresh vehicle settles by a fixed offset (see spawn-position notes)"),
    ("Static objects that are not networked (buildings, trees, terrain)", "they live in the client's level files"),
    ("Free-text chat, voice audio", "chat travels on a separate message layer (ServerStringMessageEW / StringReceivedEvent); none of the 63 game event classes, all decoded, carries chat text and no sample has any. Voice is only on/off (VoipOnOff)"),
]


def inventory(replay: Replay) -> List[Dict[str, object]]:
    """One row per category: ``events`` = how many events of its kinds the demo holds, ``items`` = how many things of ``unit``."""
    names: Dict[str, int] = {}
    for _, ev in replay.events:
        names[ev.name] = names.get(ev.name, 0) + 1
    rows = []
    for cat in CATALOG:
        events = sum(names.get(e, 0) for e in cat.events) if cat.events else None
        items = cat.count(replay) if cat.count is not None else None
        if cat.key == "settings":
            items, cat_unit = (1 if replay.server_info else 0), "block"
        elif cat.key == "map":
            items, cat_unit = (1 if replay.map_info else 0) + len(replay.map_rotation), "block + rotation entries"
        else:
            cat_unit = cat.unit
        rows.append({"key": cat.key, "title": cat.title, "exactness": cat.exactness, "events": events, "items": items,
                     "unit": cat_unit, "source": cat.source})
    return rows


def format_inventory(replay: Replay) -> str:
    lines = [f"  {'Data':<34} {'exactness':<9} {'events':>7}  {'items':<30} source"]
    for row in inventory(replay):
        events = "-" if row["events"] is None else str(row["events"])
        items = "-" if row["items"] is None else f"{row['items']} {row['unit']}"
        source = row["source"] if len(row["source"]) <= 60 else row["source"][:57] + "..."
        lines.append(f"  {row['title']:<34} {row['exactness']:<9} {events:>7}  {items:<30} {source}")
    lines.append("")
    lines.append("  Never in a demo: " + "; ".join(item for item, _ in NEVER))
    return "\n".join(lines)
