"""Compact document for the browser viewer.

The full ``--export-json`` document is far too large for a 2 hour, 64 player round (3 million pose samples, 200 MB), so the
viewer gets a reduced one: only soldiers, vehicles and supply objects, one sample every ``STEP`` ticks (the viewer
interpolates), positions in decimetres, delta encoded, heading instead of a quaternion.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from ..feed import team_name
from ..jsonexport import build_document
from ..replay import Replay
from ..tracks import Track, build_tracks

FORMAT = "bf2demo-viewer/14"
TICKS_PER_SECOND = 30
GAP_TICKS = 60      # a silence this long between two samples is a gap: the viewer holds the position instead of interpolating
STEP = 6            # keep one pose sample per 6 ticks (5 Hz)
KIT_NAMES = ["Specops", "Sniper", "Assault", "Support", "Engineer", "Medic", "AT"]
SKIP_CLASSES = {"GenericProjectile"}


def heading_degrees(q) -> Optional[int]:
    """Compass heading (0 = +z / north, clockwise) of a vehicle from its ``[x, y, z, w]`` quaternion.

    The stored quaternion is the inverse (conjugate) of the body orientation: the facing is ``q^-1 * (0, 0, 1)``. Measured against
    the movement direction of 2256 vehicle samples (jeeps, tanks, APCs, helicopters, jets of ``zxc.bf2demo``): resultant length
    0.79-0.99 and an offset of 0 +- 3 degrees for every template, against 0.13-0.3 for ``q * (0, 0, 1)``.
    """
    if q is None:
        return None
    x, y, z, w = q
    fx = 2 * (x * z - w * y)
    fz = 1 - 2 * (x * x + y * y)
    return int(round(math.degrees(math.atan2(fx, fz)))) % 360


def _encode_track(track: Track) -> Optional[Dict[str, Any]]:
    samples = track.samples
    if not samples:
        return None
    kept = []
    last = None
    for i, s in enumerate(samples):
        # keep one sample per STEP ticks, the last one, and the one before a gap (so the viewer holds the real last position)
        before_gap = i + 1 < len(samples) and samples[i + 1][0] - s[0] > GAP_TICKS
        if last is None or s[0] - last >= STEP or i == len(samples) - 1 or before_gap:
            kept.append(s)
            last = s[0]
    t0 = kept[0][0]
    dt: List[int] = []
    xs: List[int] = []
    ys: List[int] = []
    zs: List[int] = []
    hs: List[int] = []
    pt, px, py, pz = t0, 0, 0, 0
    for tick, pos, rot in kept:
        x, y, z = (int(round(c * 10)) for c in pos)
        dt.append(tick - pt)
        xs.append(x - px)
        ys.append(y - py)
        zs.append(z - pz)
        hs.append(-1 if rot is None else heading_degrees(rot))
        pt, px, py, pz = tick, x, y, z
    obj = track.obj
    items: List[int] = []
    previous = t0
    for tick, index in track.items:                       # weapon in hand: [tick delta, item index] pairs
        items += [tick - previous, index]
        previous = tick
    return {"id": obj.object_id, "cls": obj.template.cls, "tpl": obj.template.name, "owner": track.owner_id,
            "team": obj.team, "t0": t0, "end": obj.destroyed_tick, "dead": track.ragdoll_from, "wreck": track.wrecked_tick,
            "dt": dt, "x": xs, "y": ys, "z": zs, "h": hs, **({"wi": items} if items else {})}


#: barrel shells of the static artillery pieces (M777, D-30 ...) that the commander's artillery strike fires. Bombs dropped by aircraft are NOT
#: strikes (the game marks only the commander's calls), so they are not collected.
STRIKE_RE = re.compile(r"^(usart_|ars_|chart_|mecart_)", re.I)


def strike_clusters(tracks, first_tick: int = 0) -> List[Dict[str, Any]]:
    """Shells of one barrage as one marker: impacts within 80 m, each shell fired < 25 s after the previous.

    A shell counts only when it was fired during the recording (not a leftover of the join snapshot) and landed before it ended (its object was
    destroyed): the last sample of a shell still in flight is not an impact.
    """
    shells = []
    for track in tracks:
        obj = track.obj
        if not track.samples or not STRIKE_RE.search(obj.template.name):
            continue
        if obj.created_tick <= first_tick + 1 or obj.destroyed_tick is None:
            continue
        first, last = track.samples[0], track.samples[-1]
        shells.append((first[0], last[0], last[1][0], last[1][2]))
    shells.sort()
    clusters: List[Dict[str, Any]] = []
    for t0, t1, x, z in shells:
        for c in reversed(clusters[-6:]):
            if t0 - c["last_fire"] < 25 * TICKS_PER_SECOND and math.hypot(x - c["x"], z - c["z"]) < 80:
                n = c["n"]
                c["x"], c["z"] = (c["x"] * n + x) / (n + 1), (c["z"] * n + z) / (n + 1)
                c["n"], c["t1"], c["last_fire"] = n + 1, max(c["t1"], t1), t0
                break
        else:
            clusters.append({"t0": t0, "t1": t1, "x": x, "z": z, "n": 1, "last_fire": t0})
    return [{"t0": c["t0"], "t1": c["t1"], "x": round(c["x"], 1), "z": round(c["z"], 1), "kind": "artillery", "n": c["n"]} for c in clusters]


SEAT_CLASSES = {"PlayerControlObject", "Parachute"}


def seat_intervals(replay: Replay, wrecks: Optional[Dict[Any, int]] = None) -> List[Dict[str, Any]]:
    """``[{"p": player, "o": object id, "a": enter tick, "b": leave tick or None}]`` from EnterVehicle / ExitVehicle.

    A seat is closed by the player's next enter (a spawn enters the new Soldier object), by ExitVehicle, by the player leaving
    and by the vehicle being destroyed (``wrecks``: ``(object id, created tick)`` -> explosion tick, ~10 s before the object is removed;
    the occupants die at that tick); entering a Soldier object is not a seat.
    """
    wrecks = wrecks or {}
    by_id: Dict[int, list] = {}
    for obj in replay.object_history:
        by_id.setdefault(obj.object_id, []).append(obj)

    def target(object_id: int, tick: int):
        best = None
        for obj in by_id.get(object_id, ()):
            if obj.created_tick <= tick and (obj.destroyed_tick is None or tick <= obj.destroyed_tick):
                best = obj
        return best

    open_seats: Dict[int, Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []

    def close(player_id: int, tick: int) -> None:
        seat = open_seats.pop(player_id, None)
        if seat is not None:
            seat["b"] = tick
            out.append(seat)

    for tick, player_id, object_id in replay.seat_events:
        close(player_id, tick)
        if object_id is None:
            continue
        obj = target(object_id, tick)
        if obj is None:                          # a gunner / passenger seat is a nested object (root id + 1 + index): the seat of its root vehicle
            owner = replay.nested_owner(object_id, tick)
            obj = owner[0] if owner else None
        if obj is not None and obj.template is not None and obj.template.cls in SEAT_CLASSES:
            ends = [e for e in (obj.destroyed_tick, wrecks.get((obj.object_id, obj.created_tick))) if e is not None]
            open_seats[player_id] = {"p": player_id, "o": obj.object_id, "a": tick, "b": None, "end": min(ends) if ends else None}
    out.extend(open_seats.values())
    for seat in out:                    # the vehicle's destruction and the player's departure also end a seat
        ends = [e for e in (seat["b"], seat.pop("end")) if e is not None]
        seat["b"] = min(ends) if ends else None
    return sorted(out, key=lambda seat: seat["a"])


#: log kinds the viewer shows; the radio / spotting / spawn / enter-exit lines are noise for a replay and are left out of its document
FEED_KINDS = {"kill", "teamkill", "suicide", "death", "join", "leave", "kick", "team", "squad", "round", "capture", "capture-initial", "neutralize",
              "commander", "vote", "medal", "tickets", "assist", "uav"}
#: the fields of a log line's ``data`` the viewer reads
FEED_DATA = ("killer_id", "victim_id", "weapon", "weapon_template_id", "teamkill", "player_id", "team", "squad_id", "event", "object_id")
PLAYER_FIELDS = ("player_id", "name", "is_ai", "join_tick", "leave_tick", "team", "team_history", "squad_history", "kit_history", "rank_history", "score_history",
                 "stats_history", "kicked")


def slim(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only what the page reads (the full ``--export-json`` document stays available for everything else)."""
    for key in ("objects", "server_settings", "map_info"):
        doc.pop(key, None)
    doc["demo"] = {k: doc["demo"].get(k) for k in ("map", "mode", "map_size", "server", "recorded_at", "first_tick", "last_tick")}
    players = []
    for p in doc["players"]:
        item = {k: p[k] for k in PLAYER_FIELDS if k in p}
        item["leader"] = bool((p.get("state") or {}).get("is_squad_leader"))
        players.append(item)
    doc["players"] = players
    doc["feed"] = [{"tick": f["tick"], "kind": f["kind"], "text": f["text"],
                    "data": {k: f["data"][k] for k in FEED_DATA if f.get("data") and f["data"].get(k) is not None}}
                   for f in doc["feed"] if f["kind"] in FEED_KINDS]
    return doc


def kit_slots(replay: Replay) -> Dict[str, Dict[str, List[str]]]:
    """``kit template -> {item index: [weapon display names]}`` for the factions of this recording (``assets/weapon_slots.json``)."""
    import json
    import os
    from ..feed import _hud_names
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "weapon_slots.json")
    with open(path, encoding="utf-8") as fh:
        table = json.load(fh)["kits"]
    names = _hud_names()
    factions = {team_name(replay, t).lower() for t in (1, 2)}
    out: Dict[str, Dict[str, List[str]]] = {}
    for kit, slots in table.items():
        if kit.split("_", 1)[0] not in factions:
            continue
        out[kit] = {idx: list(dict.fromkeys(names.get(w) or w for w in weapons)) for idx, weapons in slots.items()}
    return out


def build_viewer_document(replay: Replay) -> Dict[str, Any]:
    doc = build_document(replay)
    doc["format"] = FORMAT
    tracks = build_tracks(replay, projectiles=True, projectile_filter=lambda name: bool(STRIKE_RE.search(name)))
    doc["strikes"] = strike_clusters(tracks.values(), replay.first_tick)
    encoded = []
    for track in sorted(tracks.values(), key=lambda t: (t.obj.created_tick, t.obj.object_id)):
        if track.obj.template.cls in SKIP_CLASSES:
            continue
        item = _encode_track(track)
        if item:
            encoded.append(item)
    doc["tracks"] = encoded
    doc["rounds"] = [{"t": t, "state": ev["begin_round_state"], "end": ev["next_state_change_tick"]} for t, ev in replay.events if ev.name == "BeginRound"]
    doc["seats"] = seat_intervals(replay, {key: t.wrecked_tick for key, t in tracks.items() if t.wrecked_tick is not None})
    doc["ticks_per_second"] = TICKS_PER_SECOND
    doc["kit_names"] = KIT_NAMES
    doc["kit_slots"] = kit_slots(replay)
    doc["team_names"] = {str(t): team_name(replay, t) for t in (1, 2)}
    doc["position_unit"] = "decimetres, delta encoded; x east, z north"
    return slim(doc)
