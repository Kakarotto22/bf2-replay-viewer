"""Game log (kill feed + server messages) and scoreboard built from a :class:`Replay`.

Text templates are the game's own English strings (``assets/hud_strings.json``:
``HUD_HUD_KILLEDBY_KILLS`` = ``#PLAYERNAME1# [#WEAPON#] #PLAYERNAME2#`` ...), weapon and
vehicle names come from the ``hudName`` keys (``assets/hud_names.json``).

Every :class:`FeedLine` says where its wording comes from:

* ``official`` - the line is the game's own string with the demo values filled in,
* ``demo`` - no game string exists for the event; the wording is ours and only states
  what the event carries.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from .postremote import decode_post_remote
from .replay import Player, Replay

_ASSETS = os.path.join(os.path.dirname(__file__), "assets")


@lru_cache(maxsize=1)
def _strings() -> Dict[str, str]:
    with open(os.path.join(_ASSETS, "hud_strings.json"), encoding="utf-8") as fh:
        return json.load(fh)["strings"]


@lru_cache(maxsize=1)
def _hud_names() -> Dict[str, str]:
    with open(os.path.join(_ASSETS, "hud_names.json"), encoding="utf-8") as fh:
        return json.load(fh)["names"]


@lru_cache(maxsize=1)
def _team_names() -> Dict[str, Dict[str, str]]:
    with open(os.path.join(_ASSETS, "team_names.json"), encoding="utf-8") as fh:
        return json.load(fh)["teams"]


def _fill(key: str, **values: str) -> str:
    text = _strings()[key]
    for name, value in values.items():
        text = text.replace(f"#{name}#", value)
    return text.strip()


@dataclass
class FeedLine:
    tick: int
    kind: str                       # kill, join, leave, kick, team, squad, round, capture, ...
    text: str
    source: str = "official"        # "official" game string or "demo" (our wording)
    data: Dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.tick:>6}] {self.text}"


class PlayerNames:
    """Resolve ``player_id`` to the name the player had at a given tick."""

    def __init__(self, replay: Replay):
        self._by_id: Dict[int, List[Player]] = {}
        for p in replay.player_history:
            self._by_id.setdefault(p.player_id, []).append(p)

    def find(self, player_id: int, tick: int) -> Optional[Player]:
        best = None
        for p in self._by_id.get(player_id, []):
            if p.join_tick <= tick and (p.leave_tick is None or tick <= p.leave_tick):
                best = p
        if best is None and self._by_id.get(player_id):
            best = self._by_id[player_id][-1]
        return best

    def name(self, player_id: int, tick: int) -> str:
        p = self.find(player_id, tick)
        if p is None:
            return f"Player#{player_id}"
        name = p.name
        for t, new in p.names:
            if t <= tick:
                name = new
        return name.strip() or f"Player#{player_id}"


def team_name(replay: Replay, team: Optional[int]) -> str:
    """``gameLogic.setTeamName`` of the level (team 1/2), e.g. ``MEC`` / ``US``."""
    if team in (1, 2):
        names = _team_names().get(replay.level)
        if names and names.get(str(team)):
            return names[str(team)]
    return {0: "Neutral", None: "?"}.get(team, f"Team {team}")


def display_name(template_id: int, replay: Replay) -> Optional[str]:
    """In-game display name of a weapon/vehicle template, or ``None``."""
    if not template_id or replay.templates is None:
        return None
    info = replay.templates.lookup(template_id)
    if info.source == "unknown":
        return None
    return _hud_names().get(info.name.lower())


def _killed_word() -> str:
    """The word of ``HUD_HUD_KILLEDBY_KILLED`` (``#PLAYERNAME1# [Killed] #PLAYERNAME2#``): what the game prints without a weapon."""
    text = _strings().get("HUD_HUD_KILLEDBY_KILLED", "")
    start, end = text.find("["), text.find("]")
    return text[start + 1:end] if 0 <= start < end else "Killed"


def kill_weapon_label(replay: Replay, ev) -> str:
    """The bracketed text of a kill line, as the game's HUD picks it (BF2.exe ``FUN_00753de0``, checked against the in-game log of ``zxc``).

    The event names a weapon template and the template of the killer's vehicle. When that vehicle is a Soldier the weapon's own
    ``weaponHud`` name is used, and a weapon without one prints nothing (the game showed ``[]`` for a bomb of an F-35B whose pilot had
    left it). Otherwise the vehicle's ``vehicleHud`` name wins over the weapon's (a jeep's machine gun is shown as the jeep; the weapon
    strings of such guns are literally ``DELETED`` in the game's table because they are never displayed), and the weapon's name is the
    fallback. A kill without any weapon template is the game's ``[Killed]``.
    """
    weapon_id, vehicle_id = ev["weapon_template_id"], ev["vehicle_template_id"]
    weapon = replay.templates.lookup(weapon_id) if weapon_id and replay.templates is not None else None
    vehicle = replay.templates.lookup(vehicle_id) if vehicle_id and replay.templates is not None else None
    names = _hud_names()
    if weapon is not None and weapon.source == "unknown":
        weapon = None
    weapon_name = names.get(weapon.name.lower()) if weapon is not None else None
    if weapon_name is not None and weapon_name.strip().upper() == "DELETED":
        weapon_name = None
    if vehicle is not None and vehicle.source != "unknown" and vehicle.cls != "Soldier":
        vehicle_name = names.get(vehicle.name.lower())
        if vehicle_name:
            return vehicle_name
    if weapon_name:
        return weapon_name
    return "" if weapon_id else _killed_word()


def kill_line(replay: Replay, names: PlayerNames, tick: int, ev) -> FeedLine:
    killer_id, victim_id = ev["attacker_id"], ev["victim_id"]
    if not ev["has_killer"]:
        # No killer player (fillKilledByData leaves the id 0): the game's kill feed prints nothing.
        victim = names.name(victim_id, tick)
        return FeedLine(tick, "death", f"{victim} died (no killer player)", "demo",
                        {"killer_id": None, "victim_id": victim_id, "shown_in_hud": False,
                         "weapon_template_id": ev["weapon_template_id"],
                         "vehicle_template_id": ev["vehicle_template_id"], "position": ev["position"]})
    killer, victim = names.name(killer_id, tick), names.name(victim_id, tick)
    kp, vp = names.find(killer_id, tick), names.find(victim_id, tick)
    weapon = kill_weapon_label(replay, ev)
    data = {"killer_id": killer_id, "victim_id": victim_id, "weapon": weapon,
            "shown_in_hud": bool(ev["has_killer"]),
            "weapon_template_id": ev["weapon_template_id"], "vehicle_template_id": ev["vehicle_template_id"],
            "position": ev["position"]}
    if killer_id == victim_id:
        return FeedLine(tick, "suicide", _fill("HUD_HUD_KILLEDBY_MYSELF", PLAYERNAME=killer), data=data)
    teamkill = kp is not None and vp is not None and kp.team_at(tick) == vp.team_at(tick) \
        and kp.team_at(tick) is not None
    data["teamkill"] = teamkill
    if weapon == _killed_word() and not ev["weapon_template_id"] and replay.templates is not None and             not display_name(ev["vehicle_template_id"], replay):
        return FeedLine(tick, "teamkill" if teamkill else "kill", _fill("HUD_HUD_KILLEDBY_KILLED", PLAYERNAME1=killer,
                                                                        PLAYERNAME2=victim), data=data)
    key = "HUD_HUD_KILLEDBY_TEAMKILLS" if teamkill else "HUD_HUD_KILLEDBY_KILLS"
    return FeedLine(tick, "teamkill" if teamkill else "kill",
                    _fill(key, PLAYERNAME1=killer, PLAYERNAME2=victim, WEAPON=weapon or ""), data=data)


def _participants(replay: Replay, names: "PlayerNames", tick: int, team: int) -> List[Tuple[str, int]]:
    """Players whose PlayerScoreData score rose at the very tick the control point changed hands.

    The server awards the capture / neutralize points (``HUD_HUD_CONQUEST_FULL_CAPTURE`` and
    ``..._NEUTRALIZE``, +2 each) in the same packet as the flag change, so these are the players that
    took part. Kills in the same tick are excluded (they also move the score).
    """
    killers = {ev["attacker_id"] for t, ev in replay.events
               if ev.name == "KilledBy" and ev["has_killer"] and abs(t - tick) <= 2}
    out = []
    for p in replay.player_history:
        if p.join_tick > tick or (p.leave_tick is not None and p.leave_tick < tick):
            continue
        if p.player_id in killers:
            continue
        before = None
        for t, v in p.score_history:
            if t < tick - 2:
                before = v
            elif t <= tick + 2 and before is not None and v > before:
                out.append((p.name.strip(), v - before))
                break
    return out


def _assists(replay: Replay, tick: int, killer: Optional[Player], victim: Optional[Player],
             capture_ticks: set) -> List[Tuple[str, int]]:
    """Kill assists, derived from PlayerScoreData.

    ``scoringCommon.onPlayerKilled`` (the game's own script) gives each assister of a kill +1 score
    (damage / targeter / driver assists; passenger assists give 0) in the same packet as the kill,
    while the kill itself gives the killer +2 (``SCORE_KILL``) and a team kill -4. So every player on
    the killer's team, other than the killer, whose score rose at the kill tick is an assister.
    The assist type (damage, targeter, driver) is not in the score and is not reported.
    """
    if killer is None or victim is None or killer is victim:
        return []
    if any(abs(c - tick) <= 2 for c in capture_ticks):
        return []                      # capture points are paid in the same packet
    out = []
    for p in replay.player_history:
        if p is killer or p.join_tick > tick or (p.leave_tick is not None and p.leave_tick < tick):
            continue
        if p.team_at(tick) != killer.team_at(tick):
            continue
        before = None
        for t, v in p.score_history:
            if t < tick - 2:
                before = v
            elif t <= tick + 2 and before is not None and v > before:
                out.append((p.name.strip(), v - before))
                break
    return out


from .timeline import format_tick  # noqa: E402


def _clock(ticks: int) -> str:
    """``mm:ss`` of a tick span (30 ticks per second, see :mod:`bf2demo.timeline`)."""
    from .timeline import format_span
    return format_span(ticks)


_GAME_STATUS = {1: "Playing", 2: "EndGame", 3: "PreGame", 4: "Paused", 5: "RestartServer", 6: "NotConnected"}
_VOTE_TYPES = {1: "map", 2: "kick player", 3: "commander"}


def _vote_line(replay: Replay, names: "PlayerNames", tick: int, ev, last: Dict[str, object]) -> Optional[FeedLine]:
    """Vote state broadcast (``ServerVoteManager::updateClientState``), de-duplicated.

    The server repeats the same state for every client request, so a line is only emitted when the
    vote's counters change. The wording is the game's own ``HUD_HUD_KICKVOTE_*_STAT`` text.
    """
    f = ev.fields
    kind = _VOTE_TYPES.get(f["vote_type"], f"type {f['vote_type']}")
    state = (f["vote_type"], f["item"], f["yes_votes"], f["no_votes"], f["votes_needed"], f["status"], f["caster"])
    if last.get("state") == state:
        return None
    last["state"] = state
    item = f["item"]
    if f["status"] == 7:
        text = f"Not enough players to start a {kind} vote"
        source = "demo"
    else:
        source = "official"
        if f["vote_type"] == 1:
            level = replay.map_rotation[item].level if item < len(replay.map_rotation) else None
            label = _strings().get(f"HUD_LEVELNAME_{level.lower()}", level) if level else f"map #{item}"
            key, values = "HUD_HUD_KICKVOTE_MAP_STAT", {"MAPNAME": label}
        elif f["vote_type"] == 2:
            key, values = "HUD_HUD_KICKVOTE_PLAYER_STAT", {"PLAYERNAME": names.name(item, tick)}
        elif f["vote_type"] == 3:
            key, values = "HUD_HUD_KICKVOTE_COMMANDER_STAT", {"PLAYERNAME": names.name(item, tick)}
        else:
            key, values = None, {}
        if key is None:
            text, source = f"Vote (type {f['vote_type']}): yes {f['yes_votes']}, no {f['no_votes']}", "demo"
        else:
            text = _fill(key, YESVOTES=str(f["yes_votes"]), NEEDED=str(f["votes_needed"]), **values)
    caster = f["caster"]
    # +0x21 is the player whose ballot triggered this broadcast; +0xc is that ballot (Vote::VoteOption 0 yes,
    # 1 no): verified on rangers001 where yes/no counters rise by one with each caster/option.
    who = ""
    if caster != 0xFF and f["votes_needed"] > 0:     # needed == 0: the vote ended, no ballot behind this update
        who = f"; last ballot: {names.name(caster, tick)} voted {'yes' if f['option'] == 0 else 'no'}"
    text += f"  [{kind} vote, no={f['no_votes']}{who}]"
    return FeedLine(tick, "vote", text, source, dict(f))


def _object_label(index: Dict[int, list], object_id: int, tick: int, names: Optional["PlayerNames"] = None) -> str:
    """``us_heavy_soldier (Viper)`` for a soldier (owner = the player who spawned into it), else template + id."""
    for obj in reversed(index.get(object_id, [])):
        if obj.created_tick <= tick and (obj.destroyed_tick is None or obj.destroyed_tick >= tick):
            label = obj.template.name if obj.template else "object"
            owner = obj.owner_id
            if owner is not None and names is not None:
                return f"{names.name(owner, tick)} ({label})"
            return f"{label} #{object_id}"
    return f"object #{object_id}"


def _remote_line(replay: Replay, names: "PlayerNames", index: Dict[int, list], tick: int, ev,
                 verbose: bool) -> Optional[FeedLine]:
    """Feed line for a ``PostRemote`` event (see :mod:`bf2demo.postremote`); ``None`` to skip."""
    r = decode_post_remote(ev)
    f = r.fields
    key = (r.category, r.event_id)
    data = {"event": r.name, **f}
    if key in ((2, 0x21), (2, 0x25)) and not verbose:
        return None             # the Commander game event already reports the change
    if key == (2, 0x21):
        who = names.find(f["player_id"], tick)
        team = f" ({team_name(replay, who.team_at(tick))})" if who is not None else ""
        return FeedLine(tick, "commander", f"{names.name(f['player_id'], tick)} became commander{team}",
                        "demo", data)
    if key == (2, 0x25):
        return FeedLine(tick, "commander", f"{names.name(f['player_id'], tick)} resigned as commander", "demo", data)
    if key == (0, 19):
        return FeedLine(tick, "uav", f"{team_name(replay, f['team'])} UAV launched (object #{f['object_id']})",
                        "demo", data)
    if key == (0, 20):
        return FeedLine(tick, "uav", f"{team_name(replay, f['team'])} UAV destroyed (object #{f['object_id']})",
                        "demo", data)
    if key == (0, 1):
        return FeedLine(tick, "round", f"Game status: {_GAME_STATUS.get(f['game_status'], f['game_status'])}",
                        "demo", data)
    if not verbose:
        return None
    if key == (6, 9):
        return FeedLine(tick, "spawn", f"{names.name(f['player_id'], tick)} spawned", "demo", data)
    if r.category == 2 and "object_a" in f:
        who = _object_label(index, f["object_a"], tick, names)
        team = team_name(replay, f["byte_10"])
        if r.event_id == 0x2b:
            return FeedLine(tick, "spot", f"[{team}] {who} spotted {_object_label(index, f['object_b'], tick, names)} "
                                          f"at x={f['x']:.0f} z={f['z']:.0f}", "demo", data)
        text = {0x2e: "called for a medic", 0x2f: "called for ammo", 0x30: "called for repair",
                0x31: "called for a revive", 0x32: "is waiting for a revive (auto call)"}.get(r.event_id)
        if text:
            return FeedLine(tick, "call", f"[{team}] {who} {text}", "demo", data)
    return None


def build_feed(replay: Replay, verbose: bool = False) -> List[FeedLine]:
    """Every server message the demo carries, in stream order.

    ``verbose`` adds vehicle enter/exit, kit pickups and VoIP toggles.
    """
    names = PlayerNames(replay)
    lines: List[FeedLine] = []
    in_snapshot = True
    last_vote: Dict[str, object] = {}
    index: Dict[int, list] = {}
    for obj in replay.object_history:
        index.setdefault(obj.object_id, []).append(obj)
    capture_ticks = {t for cp in replay.control_points.values() for t, _ in cp.history}

    for tick, ev in replay.events:
        if tick >= 0:
            in_snapshot = False
        n = ev.name
        if n == "CreatePlayer":
            who = names.name(ev["player_id"], tick)
            suffix = " (already connected when the recording began)" if in_snapshot else ""
            lines.append(FeedLine(tick, "join", f"{who} has joined the game{suffix}", "demo",
                                  {"player_id": ev["player_id"], "ai": ev["is_ai"]}))
        elif n == "DestroyPlayer":
            lines.append(FeedLine(tick, "leave", _fill("GAME_MESSAGE_PLAYER_DISCONNECTED",
                                                       PLAYERNAME=names.name(ev["player_id"], tick)),
                                  data={"player_id": ev["player_id"]}))
        elif n == "ChangePlayerName":
            p = names.find(ev["player_id"], tick)
            old = p.name.strip() if p else f"Player#{ev['player_id']}"
            lines.append(FeedLine(tick, "rename", f"{old} changed name to {ev['name'].strip()}", "demo",
                                  {"player_id": ev["player_id"]}))
        elif n == "KickBan":
            key = "HUD_TKPUNISH_banned" if ev["ban"] else "HUD_TKPUNISH_kicked"
            text = _fill(key, PLAYERNAME=names.name(ev["player_id"], tick), KEY="").replace(" ()", "")
            lines.append(FeedLine(tick, "kick", text, data={"player_id": ev["player_id"],
                                                            "reason": ev["reason"]}))
        elif n == "KilledBy":
            line = kill_line(replay, names, tick, ev)
            if not line.data["shown_in_hud"]:
                # has_killer False (this+0xe): no killer Player; BF2.exe's HUD (FUN_00753de0) prints nothing.
                if not verbose:
                    continue
                line.text += "   (not shown in the game HUD)"
            lines.append(line)
            assisters = []
            if ev["has_killer"]:
                assisters = _assists(replay, tick, names.find(ev["attacker_id"], tick),
                                     names.find(ev["victim_id"], tick), capture_ticks)
            for who, points in assisters:
                lines.append(FeedLine(tick, "assist",
                                      f"{who} got a kill assist (+{points}) on "
                                      f"{names.name(ev['victim_id'], tick)}, killed by "
                                      f"{names.name(ev['attacker_id'], tick)}", "demo",
                                      {"assister": who, "points": points, "victim_id": ev["victim_id"],
                                       "killer_id": ev["attacker_id"]}))
        elif n == "PostRemote":
            line = _remote_line(replay, names, index, tick, ev, verbose)
            if line is not None:
                lines.append(line)
        elif n == "JoinSquad":
            lines.append(FeedLine(tick, "squad", _fill("HUD_HUD_SQUAD_HAS_JOINED",
                                                       PLAYERNAME=names.name(ev["player_id"], tick))
                                  + f" (squad {ev['squad_id']}, {team_name(replay, ev['team'])})",
                                  data={"player_id": ev["player_id"], "squad_id": ev["squad_id"]}))
        elif n == "LeaveSquad":
            lines.append(FeedLine(tick, "squad", _fill("HUD_HUD_SQUAD_HAS_LEFT",
                                                       PLAYERNAME=names.name(ev["player_id"], tick))
                                  + f" (squad {ev['squad_id']}, {team_name(replay, ev['team'])})",
                                  data={"player_id": ev["player_id"], "squad_id": ev["squad_id"]}))
        elif n == "SetSquadLeader":
            lines.append(FeedLine(tick, "squad", _fill("HUD_HUD_SQUAD_NEW_SQUADLEADER",
                                                       PLAYERNAME=names.name(ev["player_id"], tick))
                                  + f" (squad {ev['squad_id']}, {team_name(replay, ev['team'])})",
                                  data={"player_id": ev["player_id"], "squad_id": ev["squad_id"]}))
        elif n == "ChangeSquadName":
            lines.append(FeedLine(tick, "squad", f"{team_name(replay, ev['team'])} squad {ev['squad_id']} "
                                                  f"is named {ev['name']!r}", "demo"))
        elif n == "SetPrivateSquad":
            lines.append(FeedLine(tick, "squad", f"{team_name(replay, ev['team'])} squad {ev['squad_id']} "
                                                  f"is now {'private' if ev['private'] else 'public'}", "demo"))
        elif n == "Rank":
            lines.append(FeedLine(tick, "rank", _fill("HUD_HUD_RANK_PROMOTED",
                                                      PLAYERNAME=names.name(ev["player_id"], tick),
                                                      RANK=str(ev["rank"])),
                                  data={"player_id": ev["player_id"], "rank": ev["rank"]}))
        elif n == "Medal":
            # BF2.exe (FUN_007bbb60) looks the name up as AWARD_Name_<id>_<level>; ribbons have no level suffix.
            strings = _strings()
            award = (strings.get(f"AWARD_Name_{ev['award_id']}_{ev['level']}")
                     or strings.get(f"AWARD_Name_{ev['award_id']}") or f"award {ev['award_id']}")
            lines.append(FeedLine(tick, "medal", f"{names.name(ev['player_id'], tick)} has been awarded: {award}",
                                  "demo", {"player_id": ev["player_id"], "award_id": ev["award_id"],
                                           "level": ev["level"]}))
        elif n == "Commander":
            if ev["action"] == 3:
                team = team_name(replay, ev["team"])
                if ev["player_id"] >= 0:
                    text = f"{names.name(ev['player_id'], tick)} is the {team} commander"
                else:
                    text = f"The {team} team has no commander"
                lines.append(FeedLine(tick, "commander", text, "demo",
                                      {"team": ev["team"], "player_id": ev["player_id"]}))
            elif verbose:
                lines.append(FeedLine(tick, "commander", f"Commander request {ev['action']} (team "
                                                         f"{team_name(replay, ev['team'])})", "demo"))
        elif n == "Vote":
            line = _vote_line(replay, names, tick, ev, last_vote)
            if line is not None:
                lines.append(line)
        elif n == "BeginRound":
            end = ev["next_state_change_tick"]
            text = "Round began" + (f" (scheduled end at tick {end}, {_clock(end - tick)} later)" if end else " (no time limit)")
            lines.append(FeedLine(tick, "round", text, "demo", dict(ev.fields)))
        elif n == "EndOfRound":
            winner = ev["winner"]
            text = (f"Round ended (winner: {team_name(replay, winner)})" if winner in (1, 2)
                    else f"Round ended (winner code {winner})")
            lines.append(FeedLine(tick, "round", text, "demo", dict(ev.fields)))
        elif verbose and n in ("EnterVehicle", "ExitVehicle"):
            who = names.name(ev["player_id"], tick)
            if n == "EnterVehicle":
                obj = replay.objects.get(ev["object_id"])
                what = obj.template.name if obj is not None and obj.template else f"object {ev['object_id']}"
                lines.append(FeedLine(tick, "vehicle", f"{who} entered {what}", "demo"))
            else:
                lines.append(FeedLine(tick, "vehicle", f"{who} left the vehicle", "demo"))

    # control point captures and player team changes come from ghost state, not events
    for cp in replay.control_points.values():
        label = cp.template.name if cp.template else f"control point {cp.object_id}"
        for i, (tick, team) in enumerate(cp.history):
            if i == 0:                  # first state the server sent, not a capture
                lines.append(FeedLine(tick, "capture-initial",
                                      f"{label} starts as {team_name(replay, team)}", "demo",
                                      {"object_id": cp.object_id}))
            else:
                who = _participants(replay, names, tick, team)
                suffix = ""
                if who:
                    suffix = " - score at this tick: " + ", ".join(f"{n} +{d}" for n, d in who)
                if team in (1, 2):
                    text = _fill("HUD_HUD_CP_CHANGED_TEAM", TEAMNAME=team_name(replay, team)) + f" ({label})"
                    kind = "capture"
                else:
                    text = f"{label} was neutralized"
                    kind = "neutralize"
                lines.append(FeedLine(tick, kind, text + suffix,
                                      "official" if team in (1, 2) else "demo",
                                      {"object_id": cp.object_id, "team": team,
                                       "players": [(n, d) for n, d in who]}))
    for p in replay.player_history:
        for i, (tick, team) in enumerate(p.team_history):
            if i == 0 and p.join_tick >= 0 and team == p.create_team:
                continue            # the team the player was created with
            if i == 0:
                continue            # state sent in the join snapshot
            lines.append(FeedLine(tick, "team", f"{p.name.strip()} changed team to {team_name(replay, team)}",
                                  "demo", {"player_id": p.player_id, "team": team}))
    if verbose:
        for team, history in sorted(replay.tickets.items()):
            last_shown = None
            for tick, value in history:
                if value == 0 and last_shown is None:
                    continue                      # the join snapshot sends 0 before the round sets the real number
                if last_shown is None or abs(value - last_shown) >= 25 or value <= 5:
                    lines.append(FeedLine(tick, "tickets", f"{team_name(replay, team)} tickets: {value}", "demo",
                                          {"team": team, "tickets": value}))
                    last_shown = value
    lines.sort(key=lambda l: l.tick)
    return lines


@dataclass
class ScoreRow:
    player: Player
    team: Optional[int]
    kills: int
    deaths: int
    teamkills: int
    suicides: int
    score: Optional[int]
    squad: Optional[int]
    kit: Optional[int]
    rank: Optional[int]


def build_scoreboard(replay: Replay) -> List[ScoreRow]:
    """One row per player occupancy.

    ``score``/``kills``/``deaths``/``teamkills`` are the game's own ``PlayerScoreData`` counters as last
    sent in the Player ghost (absolute, so they include what happened before a recording that started
    mid-round). When a player never had a counter update they are counted from the events: kills and
    teamkills from ``KilledBy`` (killer present), deaths from ``PlayerDead`` (``PostRemote`` 6/10, one per
    death even when there is no killer). ``suicides`` is always counted from ``KilledBy``.
    """
    names = PlayerNames(replay)
    stats: Dict[int, Dict[str, int]] = {}
    for tick, ev in replay.events:
        if ev.name == "PostRemote" and ev["kind"] == 6 and ev["value"] == 10:
            dead = names.find(decode_post_remote(ev).fields["player_id"], tick)
            if dead is not None:
                s = stats.setdefault(id(dead), {})
                s["deaths"] = s.get("deaths", 0) + 1
            continue
        if ev.name != "KilledBy" or not ev["has_killer"]:
            continue
        killer = names.find(ev["attacker_id"], tick)
        victim = names.find(ev["victim_id"], tick)
        if killer is None or victim is None:
            continue
        s = stats.setdefault(id(killer), {})
        if killer is victim:
            s["suicides"] = s.get("suicides", 0) + 1
        elif killer.team_at(tick) == victim.team_at(tick) and killer.team_at(tick) is not None:
            s["teamkills"] = s.get("teamkills", 0) + 1
        else:
            s["kills"] = s.get("kills", 0) + 1
    rows = []
    for p in replay.player_history:
        s = stats.get(id(p), {})
        st = p.state
        rows.append(ScoreRow(p, p.team, st.get("kills", s.get("kills", 0)), st.get("deaths", s.get("deaths", 0)),
                             st.get("teamkills", s.get("teamkills", 0)), s.get("suicides", 0),
                             st.get("score"), st.get("squad_id"), st.get("kit"), st.get("rank")))
    rows.sort(key=lambda r: (r.team or 9, -(r.score if r.score is not None else -9999), r.player.player_id))
    return rows


def format_scoreboard(replay: Replay, rows: Optional[List[ScoreRow]] = None) -> str:
    rows = rows if rows is not None else build_scoreboard(replay)
    out = []
    if replay.tickets:
        parts = [f"{team_name(replay, team)} {history[-1][1]}" for team, history in sorted(replay.tickets.items())]
        out.append("Tickets (last value sent by the ScoreManager): " + " | ".join(parts))
    for team in (1, 2, None):
        group = [r for r in rows if (r.team if r.team in (1, 2) else None) == team]
        if not group:
            continue
        out.append(f"== {team_name(replay, team) if team else 'No team'} ==")
        out.append(f"  {'ID':>3}  {'Name':<24} {'Score':>5} {'Kills':>5} {'Deaths':>6} {'TK':>3} {'Suic':>4} "
                   f"{'Squad':>5}  Status")
        for r in group:
            p = r.player
            status = "connected" if p.leave_tick is None else f"left at {format_tick(p.leave_tick, replay.first_tick)}"
            if p.kicked:
                status += " (banned)" if p.kicked[1] else " (kicked)"
            if p.is_ai:
                status += " [bot]"
            score = "?" if r.score is None else str(r.score)
            squad = "-" if r.squad is None else str(r.squad)
            out.append(f"  {p.player_id:>3}  {p.name.strip():<24} {score:>5} {r.kills:>5} {r.deaths:>6} "
                       f"{r.teamkills:>3} {r.suicides:>4} {squad:>5}  {status}")
    return "\n".join(out)
