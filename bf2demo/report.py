"""Readable report of a demo: what happened, in plain text with clock times.

Every part of the report is a *section*: a function ``(replay) -> list of lines`` registered with :func:`section`. Adding a new
part to the report is one decorated function in this module (or in any module imported before :func:`render` runs)::

    @section("flags", "Control points", "who owned which flag and when it changed hands")
    def _flags(replay):
        return [...]

``python -m bf2demo DEMO --report`` prints every section, ``--report overview,players`` a selection and
``--list-sections`` the registry. Times are ``mm:ss`` since the first simulation tick of the demo
(:mod:`bf2demo.timeline`).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from .feed import build_feed, build_scoreboard, display_name, format_scoreboard, team_name
from .replay import Replay
from .templates import resolve_vehicle_name
from .timeline import TICKS_PER_SECOND, format_span, format_tick

SectionFn = Callable[[Replay], List[str]]


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    help: str
    build: SectionFn


SECTIONS: Dict[str, Section] = {}


def section(key: str, title: str, help: str = "") -> Callable[[SectionFn], SectionFn]:
    """Register a report section (the order of registration is the order of the report)."""
    def register(fn: SectionFn) -> SectionFn:
        if key in SECTIONS:
            raise ValueError(f"report section {key!r} is registered twice")
        SECTIONS[key] = Section(key, title, help, fn)
        return fn
    return register


def render(replay: Replay, keys: Optional[Sequence[str]] = None) -> str:
    """The report as text; ``keys`` selects sections (default: all)."""
    chosen = list(keys) if keys else list(SECTIONS)
    unknown = [k for k in chosen if k not in SECTIONS]
    if unknown:
        raise KeyError(f"unknown report section(s): {', '.join(unknown)} (available: {', '.join(SECTIONS)})")
    out: List[str] = []
    for key in chosen:
        sec = SECTIONS[key]
        out.append(f"== {sec.title} ==")
        out.extend(sec.build(replay) or ["  (nothing recorded)"])
        out.append("")
    return "\n".join(out)


def list_sections() -> str:
    return "\n".join(f"  {s.key:<10} {s.title}: {s.help}" for s in SECTIONS.values())


# ---------------------------------------------------------------------------------------------------------- helpers
def _origin(replay: Replay) -> Optional[int]:
    return replay.first_tick


def _clock(replay: Replay, tick: int) -> str:
    return format_tick(tick, _origin(replay))


def _duration(replay: Replay) -> int:
    if replay.first_tick is None or replay.last_tick is None:
        return 0
    return replay.last_tick - replay.first_tick


def _vehicle_label(name: str) -> str:
    pretty = resolve_vehicle_name(name)
    return f"{pretty} ({name})" if pretty and pretty != name else name


def _ending(replay: Replay) -> Optional[str]:
    """What the last seconds of the recording show about the end of the round (inferred: the recorder stops before EndOfRound)."""
    if not replay.tickets or replay.last_tick is None:
        return None
    last = {team: history[-1] for team, history in replay.tickets.items() if history}
    low = [team for team, (tick, value) in last.items() if 0 < value <= 30 and replay.last_tick - tick <= 3]
    if not low:
        return None
    loser = low[0]
    other = [t for t in last if t != loser]
    held = [cp for cp in replay.control_points.values() if cp.history and cp.history[-1][1] != loser and cp.history[-1][1] in (1, 2)]
    flags = f", {len(held)} of {len(replay.control_points)} flags held by the other team" if held else ""
    return (f"tickets of {team_name(replay, loser)} were down to {last[loser][1]} when the recording stopped "
            f"({_clock(replay, replay.last_tick)})" + (f" against {last[other[0]][1]}" if other else "") + flags
            + " - the round was ending (inferred: the recorder stops before the EndOfRound event is sent)")


# ---------------------------------------------------------------------------------------------------------- sections
@section("overview", "Overview", "server, map, length of the recording, round schedule")
def _overview(replay: Replay) -> List[str]:
    h = replay.demo.header
    lines = [f"  Server        {replay.server_name or h.server_name}",
             f"  Recorded      {h.recorded_at} (engine {h.version})",
             f"  Map           {h.map_name}, {replay.game_mode or '?'}, {replay.map_size or '?'} players",
             f"  Length        {format_span(_duration(replay))} ({_duration(replay)} ticks at {TICKS_PER_SECOND} per second)"]
    rounds = [(t, ev) for t, ev in replay.events if ev.name == "BeginRound"]
    if rounds:
        tick, ev = rounds[0]
        end = ev["next_state_change_tick"]
        lines.append(f"  Round         began at {_clock(replay, tick)}; "
                     + (f"scheduled to end {format_span(end - tick)} later (time limit)" if end else "no time limit"))
    ending = _ending(replay)
    if ending:
        lines.append("  Ending        " + ending)
    if replay.map_rotation:
        current = replay.current_map
        lines.append("  Map rotation  " + ", ".join(
            f"{'[' if i == current else ''}{m.level}/{m.mode}/{m.size}{']' if i == current else ''}"
            for i, m in enumerate(replay.map_rotation)))
    stats = collections.Counter(ev.name for _, ev in replay.events)
    lines.append(f"  Events        {sum(stats.values())} of {len(stats)} kinds; packets {len(replay.demo.packets)}, "
                 f"undecodable {len(replay.packet_errors)}")
    return lines


@section("settings", "Server settings", "the rules the server announced when the recording began (DataBlock kind 0)")
def _settings(replay: Replay) -> List[str]:
    info = replay.server_info
    if not info:
        return []
    yes = lambda v: "on" if v else "off"                       # noqa: E731
    limit = info["time_limit"]
    lines = [f"  Rounds per map      {info['rounds_per_map']}",
             f"  Time limit          {format_span(limit * TICKS_PER_SECOND) if limit else 'none'}",
             f"  Spawn time          {info['spawn_time']} s",
             f"  Ticket ratio        {info['ticket_ratio']} %, team ratio {info['team_ratio_percent']} %",
             f"  Vehicles            {'disabled' if info['no_vehicles'] else 'enabled'}",
             f"  Auto balance        {yes(info['auto_balance_team'])}, global unlocks {yes(info['use_global_unlocks'])}",
             f"  Voting              {yes(info['voting_enabled'])} (team only: {yes(info['team_vote_only'])})",
             f"  Team kill punish    {yes(info['tk_punish_by_default'])}, friendly fire with mines {yes(info['friendly_fire_with_mines'])}",
             f"  Cameras             free {yes(info['allow_free_cam'])}, external {yes(info['allow_external_views'])}, "
             f"nose {yes(info['allow_nose_cam'])}, hit indicator {yes(info['hit_indicator'])}",
             f"  Voip                {'remote server' if info['voip_server_remote'] else 'local'}, "
             f"port {info['voip_server_port']}, quality {info['voip_quality']}",
             f"  Co-op bots          {info['coop_bot_count']} at difficulty {info['coop_bot_difficulty']} (ratio {info['coop_bot_ratio']})"]
    for text in info["welcome_message"]:
        if text.strip():
            lines.append("  Welcome message     " + " | ".join(part.strip() for part in text.split("|") if part.strip()))
    return lines


@section("teams", "Teams and tickets", "tickets at start, end and lowest point per team")
def _teams(replay: Replay) -> List[str]:
    if not replay.tickets:
        return ["  no ScoreManager ticket updates in this demo"]
    lines = []
    for team, history in sorted(replay.tickets.items()):
        live = [item for item in history if item[1] > 0] or history      # the manager first sends 0 before the real value
        low_tick, low = min(live, key=lambda item: item[1])
        lines.append(f"  {team_name(replay, team):<10} start {live[0][1]:>4}  end {history[-1][1]:>4}  lowest {low:>4} at "
                     f"{_clock(replay, low_tick)}  ({len(history)} updates)")
    return lines


@section("players", "Players", "scoreboard of every player slot that appeared in the recording")
def _players(replay: Replay) -> List[str]:
    rows = build_scoreboard(replay)
    if not rows:
        return []
    return ["  " + line for line in format_scoreboard(replay, rows).splitlines()]


@section("flags", "Control points", "owner at the start, every change of owner with its time")
def _flags(replay: Replay) -> List[str]:
    lines = []
    for cp in sorted(replay.control_points.values(), key=lambda c: c.template.name if c.template else ""):
        name = cp.template.name if cp.template else f"object {cp.object_id}"
        pos = "?" if not cp.position else "/".join(f"{c:.0f}" for c in cp.position)
        flags = "" if all(cp.allow_capture) else "  (cannot be captured)"
        lines.append(f"  {name}  at {pos}{flags}")
        trail = [f"{_clock(replay, tick)} {team_name(replay, team)}" for tick, team in cp.history]
        lines.append("      " + (" -> ".join(trail) if trail else "no owner information"))
    return lines


@section("vehicles", "Vehicles and emplacements", "what was created, destroyed and entered")
def _vehicles(replay: Replay) -> List[str]:
    seen: Dict[str, Dict[str, int]] = collections.defaultdict(lambda: collections.Counter())
    for obj in replay.object_history:
        info = obj.template
        if info is None or info.cls != "PlayerControlObject":
            continue
        row = seen[info.name]
        row["objects"] += 1
        row["destroyed"] += obj.destroyed_tick is not None
        row["entered"] += len(obj.enters)
    if not seen:
        return []
    lines = [f"  {'Vehicle':<44} {'objects':>7} {'destroyed':>9} {'entered':>7}"]
    for name, row in sorted(seen.items(), key=lambda kv: -kv[1]["objects"]):
        lines.append(f"  {_vehicle_label(name):<44} {row['objects']:>7} {row['destroyed']:>9} {row['entered']:>7}")
    return lines


@section("weapons", "Projectiles", "launched projectiles by type (rockets, missiles, grenades that the server announces)")
def _weapons(replay: Replay) -> List[str]:
    count: collections.Counter = collections.Counter()
    for tick, ev in replay.events:
        if ev.name != "MissileInit":
            continue
        obj = replay.object_at(ev["object_id"], tick)
        label = display_name(obj.template_id, replay) if obj is not None else None
        count[label or (obj.template.name if obj is not None and obj.template else "unknown")] += 1
    return [f"  {n:>5}  {name}" for name, n in count.most_common()]


@section("radio", "Radio calls and spotting", "who called for a medic, ammo, repair or revive and who spotted what (per player)")
def _radio(replay: Replay) -> List[str]:
    import re
    kinds = ("CallForMedic", "CallForAmmo", "CallForRepair", "CallForRevive", "AutoCallForRevive", "UnitSpotted")
    table: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for line in build_feed(replay, verbose=True):
        event = line.data.get("event") if line.kind in ("call", "spot") else None
        if event in kinds:
            match = re.match(r"^\[[^\]]*\] (.*?) \(", line.text) or re.match(r"^\[[^\]]*\] (.*?) (?:called|spotted|is waiting)", line.text)
            table[match.group(1) if match else "?"][event] += 1
    if not table:
        return []
    lines = [f"  {'Player':<28} {'medic':>5} {'ammo':>5} {'repair':>6} {'revive':>6} {'auto':>5} {'spots':>5}"]
    for who, c in sorted(table.items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(f"  {who[:28]:<28} {c['CallForMedic']:>5} {c['CallForAmmo']:>5} {c['CallForRepair']:>6} "
                     f"{c['CallForRevive']:>6} {c['AutoCallForRevive']:>5} {c['UnitSpotted']:>5}")
    lines.append("  (the server relays these as HUD events; the separate RadioMessage event and chat text never appear in a recording)")
    return lines


@section("squads", "Squads and invitations", "squad membership over time per player and the invitations they received")
def _squads(replay: Replay) -> List[str]:
    lines = []
    end = replay.last_tick
    for p in replay.player_history:
        spans = []
        history = p.squad_history
        for i, (tick, squad) in enumerate(history):
            if squad in (None, 0):
                continue
            until = history[i + 1][0] if i + 1 < len(history) else (p.leave_tick if p.leave_tick is not None else end)
            spans.append(f"squad {squad} {_clock(replay, tick)}-{_clock(replay, until)}")
        invites = []
        for tick, mask in p.invite_history:
            squads = [n for n in range(32) if mask >> n & 1]
            if squads:
                invites.append(f"{_clock(replay, tick)} invited by squad {', '.join(map(str, squads))}")
        if spans or invites:
            lines.append(f"  [{team_name(replay, p.team)}] {p.name.strip()}")
            if spans:
                lines.append("      " + "; ".join(spans))
            if invites:
                lines.append("      " + "; ".join(invites))
    for tick, ev in replay.events:
        if ev.name == "SetSquadLeader":
            lines.append(f"  {_clock(replay, tick)} new squad leader in squad {ev['squad_id']} ({team_name(replay, ev['team'])}), player {ev['player_id']}")
    return lines


@section("commander", "Commander tools", "UAVs, supply crates, parachute drops, artillery and commander changes")
def _commander(replay: Replay) -> List[str]:
    kinds = {"uav_pred": "UAV", "supply_crate": "supply crate", "parachute": "parachute (drop)"}
    lines = []
    count: collections.Counter = collections.Counter()
    first: Dict[str, int] = {}
    for obj in replay.object_history:
        name = obj.template.name if obj.template else ""
        label = kinds.get(name) or ("air drop" if "AirDrop" in name else None)
        if label and not obj.snapshot:
            count[label] += 1
            first.setdefault(label, obj.created_tick)
    for label, n in count.most_common():
        lines.append(f"  {label:<18} {n:>4} created during the recording, first at {_clock(replay, first[label])}")
    artillery = sum(1 for _, ev in replay.events if ev.name == "Artillery" and ev["mode"] == 2)
    if artillery:
        lines.append(f"  {'artillery':<18} {artillery:>4} control updates (a commander takes an artillery piece)")
    for line in build_feed(replay):
        if line.kind in ("commander", "uav"):
            lines.append(f"  {format_tick(line.tick, _origin(replay))}  {line.text}")
    return lines


@section("timeline", "Key moments", "round, flag captures, votes, commander, kicks (not the individual kills)")
def _timeline(replay: Replay) -> List[str]:
    keep = {"round", "capture", "vote", "commander", "kick", "team"}
    lines = []
    for line in build_feed(replay):
        if line.kind in keep:
            lines.append(f"  {format_tick(line.tick, _origin(replay))}  {line.text}")
    return lines


@section("events", "Event catalogue", "every event kind of this demo with its count")
def _events(replay: Replay) -> List[str]:
    counts = collections.Counter(ev.name for _, ev in replay.events)
    return [f"  {n:>6}  {name}" for name, n in counts.most_common()]
