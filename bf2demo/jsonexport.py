"""JSON export of everything the parser recovers from a demo (game log, players, scoreboard, tickets, control points, objects,
optionally the object tracks and the vehicle element states).

The document is plain JSON: positions are ``[x, y, z]`` world metres, rotations quaternions ``[x, y, z, w]`` (tracks) or Euler
``[yaw, pitch, roll]`` degrees as sent in ``CreateObjectEvent`` (objects), ticks are ghost ticks (1/30 s).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, List, Optional

from .feed import PlayerNames, build_feed, build_scoreboard, team_name
from .replay import Replay

FORMAT = "bf2demo-json/2"


def _plain(value: Any) -> Any:
    """Convert dataclasses, tuples, bytes and unknown objects into JSON-friendly values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float) and value != value:
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _player(replay: Replay, p) -> Dict[str, Any]:
    return {
        "player_id": p.player_id, "ghost_id": p.ghost_id, "name": p.name, "is_ai": p.is_ai, "is_remote": p.is_remote,
        "join_tick": p.join_tick, "leave_tick": p.leave_tick, "team": p.team, "team_name": team_name(replay, p.team),
        "names": _plain(p.names), "team_history": _plain(p.team_history), "squad_history": _plain(p.squad_history),
        "kit_history": _plain(p.kit_history), "rank_history": _plain(p.rank_history), "invite_history": _plain(p.invite_history), "score_history": _plain(p.score_history), "stats_history": _plain(p.stats_history), "state": _plain(p.state),
        "kicked": None if p.kicked is None else {"tick": p.kicked[0], "banned": bool(p.kicked[1])},
    }


def build_document(replay: Replay, tracks: Optional[dict] = None, parts: bool = False) -> Dict[str, Any]:
    """The document as a dict. ``tracks`` (from ``tracks.build_tracks``) adds pose samples; ``parts`` also their element states."""
    h = replay.demo.header
    names = PlayerNames(replay)
    doc: Dict[str, Any] = {
        "format": FORMAT,
        "demo": {"engine_version": h.version, "recorded_at": h.recorded_at, "server": replay.server_name or h.server_name,
                 "map": h.map_name, "mode": replay.game_mode, "map_size": replay.map_size,
                 "first_tick": replay.first_tick, "last_tick": replay.last_tick, "packets": len(replay.demo.packets),
                 "undecodable_packets": len(replay.packet_errors), "notes": list(replay.demo.notes),
                 "map_rotation": _plain(replay.map_rotation)},
        "server_settings": _plain(replay.server_info),
        "map_info": _plain(replay.map_info),
        "players": [_player(replay, p) for p in replay.player_history],
        "feed": [{"tick": line.tick, "kind": line.kind, "text": line.text, "source": line.source, "data": _plain(line.data)}
                 for line in build_feed(replay, verbose=True)],
        "scoreboard": [{"player_id": r.player.player_id, "name": r.player.name, "team": r.team,
                        "team_name": team_name(replay, r.team), "score": r.score, "kills": r.kills, "deaths": r.deaths,
                        "teamkills": r.teamkills, "suicides": r.suicides, "squad": r.squad, "kit": r.kit, "rank": r.rank,
                        "join_tick": r.player.join_tick, "leave_tick": r.player.leave_tick}
                       for r in build_scoreboard(replay)],
        "tickets": {str(team): _plain(history) for team, history in sorted(replay.tickets.items())},
        "control_points": [{"object_id": cp.object_id, "template": cp.template.name if cp.template else None,
                            "position": _plain(cp.position), "initial_team": cp.initial_team, "team": cp.team,
                            "history": _plain(cp.history)} for cp in replay.control_points.values()],
        "objects": [{"object_id": o.object_id, "template": o.template.name if o.template else None,
                     "class": o.template.cls if o.template else None, "team": o.team, "position": _plain(o.position),
                     "rotation": _plain(o.rotation), "created_tick": o.created_tick, "destroyed_tick": o.destroyed_tick,
                     "from_join_snapshot": o.snapshot,
                     "owner_player_id": o.owner_id} for o in replay.object_history],
    }
    if tracks is not None:
        out: List[Dict[str, Any]] = []
        for track in sorted(tracks.values(), key=lambda t: (t.obj.created_tick, t.obj.object_id)):
            obj = track.obj
            entry: Dict[str, Any] = {
                "object_id": obj.object_id, "created_tick": obj.created_tick, "template": obj.template.name,
                "class": obj.template.cls, "owner_player_id": track.owner_id,
                "owner_name": names.name(track.owner_id, obj.created_tick) if track.owner_id is not None else None,
                "ragdoll_from": track.ragdoll_from,
                "samples": [[tick, *(round(c, 4) for c in pos), *([] if rot is None else (round(c, 5) for c in rot))]
                            for tick, pos, rot in track.samples],
            }
            if parts and track.parts:
                entry["parts"] = [{"tick": tick, "scope": "root" if scope == 0 else f"seat{scope}", "element": element,
                                   "kind": kind, "values": _plain(values)} for tick, scope, element, kind, values in track.parts]
            out.append(entry)
        doc["track_sample_layout"] = "[tick, x, y, z, qx, qy, qz, qw] (quaternion absent when unknown)"
        doc["tracks"] = out
    return doc


def write_json(replay: Replay, path: str, tracks: Optional[dict] = None, parts: bool = False, indent: Optional[int] = None) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_document(replay, tracks, parts), fh, ensure_ascii=False, indent=indent,
                  separators=None if indent else (",", ":"))
