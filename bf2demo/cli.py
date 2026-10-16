"""Command line interface for the bf2demo parser."""

from __future__ import annotations

import argparse
import collections
import os

from .reader import load_demo
from .replay import Replay, build_replay
from .templates import resolve_vehicle_name

TEAM_NAMES = {0: "Neutral", 1: "Team 1", 2: "Team 2"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bf2demo",
        description="Parse Battlefield 2 (.bf2demo) Refractor 2 replays.",
    )
    parser.add_argument("demo", help="path to a .bf2demo file")
    parser.add_argument("--report", nargs="?", const="all", metavar="SECTIONS",
                        help="readable report with clock times: all sections, or a comma separated selection "
                             "(see --list-sections); printed by default when no other output is requested")
    parser.add_argument("--inventory", action="store_true",
                        help="list every kind of data a demo can hold and how much of it this demo has")
    parser.add_argument("--list-sections", action="store_true", help="list the sections of --report and exit")
    parser.add_argument("--map-info", action="store_true",
                        help="print control points and vehicle spawn sites")
    parser.add_argument("--events", action="store_true", help="print every decoded game event")
    parser.add_argument("--feed", action="store_true",
                        help="print the game log: kill feed, joins/disconnects, kicks, squads, ranks, captures")
    parser.add_argument("--feed-verbose", action="store_true",
                        help="--feed plus vehicle enter/exit lines")
    parser.add_argument("--scoreboard", action="store_true",
                        help="print the players of the recording grouped by team")
    parser.add_argument("--tracks", action="store_true",
                        help="print where each soldier/vehicle went (samples, distance, owner player)")
    parser.add_argument("--export-tracks", metavar="OUT.csv",
                        help="write every pose sample (tick, object, owner, x y z, quaternion) as CSV")
    parser.add_argument("--export-parts", metavar="OUT.csv",
                        help="write vehicle element states in physical units (turret/rotor/control-surface angles in degrees, "
                             "engine values) as long-format CSV")
    parser.add_argument("--export-json", metavar="OUT.json",
                        help="write the game log, players, scoreboard, tickets, control points and objects as JSON "
                             "(add --json-tracks / --json-parts for pose samples and vehicle element states)")
    parser.add_argument("--json-tracks", action="store_true", help="include the object pose tracks in --export-json")
    parser.add_argument("--json-parts", action="store_true",
                        help="include vehicle element states (physical units) in --export-json (implies --json-tracks)")
    parser.add_argument("--json-indent", type=int, default=None, help="pretty-print --export-json with this indent")
    parser.add_argument("--export-static", metavar="OUT.con",
                        help="write the networked static objects (destructible bridges, crates, barrels, doors ...) "
                             "as StaticObjects.con text")
    parser.add_argument("--export-con", metavar="OUT.con",
                        help="write a GamePlayObjects.con reconstructed from the demo")
    parser.add_argument("--merge", action="append", default=[], metavar="DEMO",
                        help="with --export-con: add more recordings of the same map as evidence (repeatable): spawn points "
                             "need two spawns at one position, exact vehicle spawners need a respawn during a recording")
    parser.add_argument("--clip", metavar="OUT.bf2demo",
                        help="write the recording cut at --clip-end (safe) and/or starting at --clip-start (experimental: the packets before "
                             "the clip are squashed into one tick so the game applies them at once); times are seconds since the round start")
    parser.add_argument("--clip-start", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--clip-end", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--no-signature", action="store_true",
                        help="--clip: do not put the BF2Demo Analyzer welcome message into the clip (default: put it)")
    parser.add_argument("--clip-lead", type=float, default=8.0, metavar="SECONDS",
                        help="seconds before --clip-start that still play normally (default 8)")
    parser.add_argument("--min-spawn-count", type=int, default=2,
                        help="soldier spawns needed at a position to export it as a SpawnPoint")
    parser.add_argument("--include-single", action="store_true",
                        help="also export vehicles created once at a unique spot (drops look like this)")
    parser.add_argument("--layout", metavar="REF.con",
                        help="use this GamePlayObjects.con as the static-text layout instead of the "
                             "bundled retail one (e.g. the original file of a custom map)")
    parser.add_argument("--no-layout", action="store_true",
                        help="do not use any layout: names/order are generated")
    parser.add_argument("--drop-unobserved", action="store_true",
                        help="remove layout objects the demo never showed (default: keep them unchanged)")
    parser.add_argument("--allow-new-templates", action="store_true",
                        help="add objects the layout cannot describe as NEW object templates (they shift every later template "
                             "id: clients that have the original map files then desynchronise)")
    parser.add_argument("--keep-absent-spawners", action="store_true",
                        help="keep spawners that a map-load snapshot proves are missing from the recorded map")
    parser.add_argument("--placeholder-spawn-points", action="store_true",
                        help="write one placeholder spawn point (at the group centroid, flag height) for every spawn group the demo "
                             "announces but no soldier spawned in")
    parser.add_argument("--estimate-settle", action="store_true",
                        help="ESTIMATE the spawner Y of mobile vehicles that already existed when the recording "
                             "began (their exact Y is not in the demo); default: write the snapshot value, "
                             "flagged approximate")
    parser.add_argument("--author", default=None,
                        help="modifiedByUser value for objects that exist only in the demo")
    parser.add_argument("--cp-ids", default=None,
                        help="comma separated controlPointId per control point (no-layout mode)")
    parser.add_argument("--layer", type=int, default=None,
                        help="Object.layer written to the .con (default: by mode/size)")
    return parser


def _fmt_pos(pos) -> str:
    """Position in GamePlayObjects.con notation (``x/y/z``, 3 decimals)."""
    if not pos:
        return "?"
    return "/".join(f"{c:.3f}" for c in pos)


def _team(team) -> str:
    return TEAM_NAMES.get(team, str(team)) if team is not None else "?"


def _display(name: str) -> str:
    pretty = resolve_vehicle_name(name)
    return f"{name} [{pretty}]" if pretty and pretty != name else name


def print_summary(replay: Replay) -> None:
    h = replay.demo.header
    db = replay.templates
    print(f"Demo:    engine {h.version}, recorded {h.recorded_at}")
    print(f"Server:  {replay.server_name or h.server_name}")
    print(f"Map:     {h.map_name}  mode={replay.game_mode or '?'}  "
          f"size={replay.map_size or '?'}  layer={db.layer or '?'}"
          f"{'' if db.aligned else '  (level templates not aligned)'}")
    print(f"Ticks:   {replay.first_tick}..{replay.last_tick}  packets={len(replay.demo.packets)}"
          f"  undecodable={len(replay.packet_errors)}")
    counts = collections.Counter(ev.name for _, ev in replay.events)
    print("Events:  " + ", ".join(f"{k}={v}" for k, v in counts.most_common()))
    for note in replay.demo.notes:
        print(f"Note:    {note}")


def print_map_info(replay: Replay) -> None:
    cps = list(replay.control_points.values())
    print(f"CONTROL POINTS [{len(cps)}] (created transform and owners from the demo):")
    for cp in cps:
        changes = f"  captures={len(cp.history) - 1}" if len(cp.history) > 1 else ""
        start, end = _team(cp.initial_team), _team(cp.team)
        owner = start if start == end else f"{start} -> {end}"
        uncap = "" if all(cp.allow_capture) else "  (uncapturable)"
        print(f"  {cp.template.name}")
        print(f"      absolutePosition {_fmt_pos(cp.position)}  owner {owner}{uncap}{changes}")
    sites = replay.spawn_sites
    exact = sum(1 for s in sites if s.exact)
    print(f"VEHICLE SPAWNERS [{len(sites)}] ({exact} exact: vehicle created during the recording "
          f"or static object; snapshot = mobile vehicle's current transform when recording began):")
    for site in sites:
        names = [f"{_display(n)} x{c}" if c > 1 else _display(n) for n, c in site.templates.items()]
        names += [f"{_display(n)} (snapshot)" for n in site.snapshot_templates
                  if n not in site.templates]
        kind = "exact   " if site.exact else "snapshot"
        lone = "" if site.confirmed else "  [single creation: not confirmed as a spawner]"
        near = f"  near {site.nearest_cp.template.name}" if site.nearest_cp else ""
        print(f"  [{kind}] absolutePosition {_fmt_pos(site.position)}  rotation "
              f"{_fmt_pos(site.rotation)}{near}")
        print(f"             {' | '.join(names)}{lone}")


def print_events(replay: Replay) -> None:
    for tick, ev in replay.events:
        fields = ", ".join(f"{k}={v!r}" for k, v in ev.fields.items())
        print(f"{tick:>8} {ev.name}: {fields}")


_OUTPUT_FLAGS = ("report", "inventory", "map_info", "events", "scoreboard", "tracks", "export_tracks", "export_parts", "export_json", "feed",
                 "feed_verbose", "export_static", "export_con", "clip")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_sections:
        from .report import list_sections
        print(list_sections())
        return 0
    if not os.path.isfile(args.demo):
        parser.error(f"file not found: {args.demo}")
    if args.merge and not args.export_con:
        parser.error("--merge only applies to --export-con")
    demo = load_demo(args.demo)
    replay = build_replay(demo)
    print_summary(replay)
    if args.clip:
        from .clip import TICKS_PER_SECOND, make_clip
        first = replay.first_tick or 0
        start = None if args.clip_start is None else first + round(args.clip_start * TICKS_PER_SECOND)
        end = None if args.clip_end is None else first + round(args.clip_end * TICKS_PER_SECOND)
        with open(args.clip, "wb") as fh:
            fh.write(make_clip(demo, start, end, args.clip_lead, not args.no_signature))
        print(f"Wrote {args.clip}")
    if args.report or not any(getattr(args, name) for name in _OUTPUT_FLAGS):
        from .report import render
        keys = None if args.report in (None, "all") else [k.strip() for k in args.report.split(",") if k.strip()]
        try:
            print(render(replay, keys))
        except KeyError as exc:
            parser.error(exc.args[0])
    if args.inventory:
        from .inventory import format_inventory
        print("Data in this demo")
        print(format_inventory(replay))
    if args.map_info:
        print_map_info(replay)
    if args.events:
        print_events(replay)
    if args.scoreboard:
        from .feed import format_scoreboard
        print("Scoreboard (players of the recording)")
        print(format_scoreboard(replay))
    if args.tracks or args.export_tracks or args.export_parts:
        from .tracks import build_tracks, format_tracks, write_parts_csv, write_tracks_csv
        tracks = build_tracks(replay, parts=bool(args.export_parts))
        if args.tracks:
            print("Object tracks")
            print(format_tracks(replay, tracks))
        if args.export_tracks:
            write_tracks_csv(replay, tracks, args.export_tracks)
            print(f"Wrote {args.export_tracks}")
        if args.export_parts:
            write_parts_csv(replay, tracks, args.export_parts)
            print(f"Wrote {args.export_parts}")
    if args.export_json:
        from .jsonexport import write_json
        doc_tracks = None
        if args.json_tracks or args.json_parts:
            from .tracks import build_tracks
            doc_tracks = build_tracks(replay, parts=args.json_parts)
        write_json(replay, args.export_json, doc_tracks, args.json_parts, args.json_indent)
        print(f"Wrote {args.export_json}")
    if args.feed or args.feed_verbose:
        from .feed import build_feed
        print("Game log")
        for line in build_feed(replay, verbose=args.feed_verbose):
            print(f"  {line}")
    if args.export_static:
        from .export_static import export_static_objects
        with open(args.export_static, "w", encoding="latin1", newline="") as fh:
            fh.write(export_static_objects(replay))
        print(f"Wrote {args.export_static}")
    if args.export_con:
        from .export_con import ExportOptions, export_gameplay_objects
        if args.merge:
            from .merge import merge_replays
            for path in args.merge:
                if not os.path.isfile(path):
                    parser.error(f"file not found: {path}")
            try:
                replay = merge_replays([replay] + [build_replay(load_demo(path)) for path in args.merge])
            except ValueError as exc:
                parser.error(str(exc))
        layout = None
        if args.layout:
            with open(args.layout, "r", encoding="latin1") as fh:
                layout = fh.read()
        cp_ids = [int(v) for v in args.cp_ids.split(",")] if args.cp_ids else None
        options = ExportOptions(args.min_spawn_count, args.layer,
                                f'"{args.author}"' if args.author else None, cp_ids,
                                args.include_single, layout, not args.no_layout, not args.drop_unobserved,
                                args.estimate_settle, not args.keep_absent_spawners, args.allow_new_templates,
                                args.placeholder_spawn_points)
        text = export_gameplay_objects(replay, options)
        with open(args.export_con, "w", encoding="latin1", newline="") as fh:
            fh.write(text.replace(chr(10), chr(13) + chr(10)))
        print(f"Wrote {args.export_con}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
