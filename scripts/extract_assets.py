"""One-time extractor: build bf2demo/assets/canonical_assets.json from the game.

Reads the installed Battlefield 2 level ``server.zip`` archives and its
localisation ``.utxt`` files, and emits a single canonical JSON definition
consumed at runtime by :mod:`bf2demo.templates` (display names).

This script is a development/extraction tool. The runtime parser never touches
the game installation; it only reads the bundled JSON.

Usage::

    python scripts/extract_assets.py [game_root] [output_path]
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile

DEFAULT_GAME = r"C:\Program Files (x86)\EA Games\Battlefield 2"
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "..", "bf2demo", "assets", "canonical_assets.json")

#: Immutable vehicle classification categories (ordered category -> substrings).
VEHICLE_CATEGORIES = [
    ["heli", ["air_", "ah1", "ah-1", "z10", "wz10", "wz-10", "heli", "cobra", "mi-28"]],
    ["jet", ["ruair", "usair", "eurofighter", "j10", "j-10", "f35", "f-35", "su-"]],
    ["tank", ["tnk", "tank", "t90", "abrams", "type98", "type99", "ztz", "leopard"]],
    ["aav", ["aav", "tunguska", "aa_", "lav-ad"]],
    ["apc", ["apc", "lav25", "lav-25", "wz551", "wz-551", "btr"]],
    ["car", ["jep", "jeep", "hmmwv", "vodnik", "faav", "dune", "buggy", "vulcan"]],
    ["boat", ["boat", "rib", "pbr", "hovercraft"]],
    ["emplacement", ["ats", "igla", "stinger", "tow", "hj8", "hj-8", "bipod", "mg_", "mortar"]],
    ["artillery", ["howitzer", "artillery", "d30", "d-30", "m777", "lw155", "smerch"]],
]

_LP = re.compile(r"^(\w+) (.+)$")
_CREATE_OBJ = re.compile(r"^ObjectTemplate\.create (ObjectSpawner|SpawnPoint|ControlPoint) (\w+)")
_OBJ_CREATE = re.compile(r"^Object\.create (\w+)")
_OBJ_POS = re.compile(r"^Object\.absolutePosition ([-0-9.]+)/([-0-9.]+)/([-0-9.]+)")
_CP_ID = re.compile(r"^ObjectTemplate\.controlPointId (\d+)")
_CP_TEAM = re.compile(r"^ObjectTemplate\.team (\d+)")
_CP_NAME = re.compile(r"^ObjectTemplate\.setControlPointName (\w+)")


def _parse_con(text: str) -> dict:
    """Parse a GamePlayObjects.con into templates + placed objects."""
    templates: dict = {}
    placed: list = []
    current_template = None
    current_create = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _CREATE_OBJ.match(line)
        if m:
            current_template = {"type": m.group(1), "name": m.group(2)}
            templates[m.group(2)] = current_template
            continue
        if current_template is not None:
            m = _CP_ID.match(line)
            if m:
                current_template["control_point_id"] = int(m.group(1))
            m = _CP_TEAM.match(line)
            if m:
                current_template["team"] = int(m.group(1))
            m = _CP_NAME.match(line)
            if m:
                current_template["control_point_name"] = m.group(1)
            m = re.match(r"^ObjectTemplate\.setObjectTemplate (\d+) (\w+)", line)
            if m:
                current_template.setdefault("spawn_vehicles", {})[int(m.group(1))] = m.group(2)
        m = _OBJ_CREATE.match(line)
        if m:
            current_create = {"name": m.group(1)}
            placed.append(current_create)
            continue
        if current_create is not None:
            m = _OBJ_POS.match(line)
            if m:
                current_create["pos"] = [float(x) for x in m.groups()]
            elif line.startswith("Object.rotation"):
                parts = line.split()[1].split("/")
                try:
                    current_create["rot"] = [float(x) for x in parts]
                except ValueError:
                    pass
    return {"templates": templates, "placed": placed}


def _iter_level_archives(game_root: str):
    levels_dir = os.path.join(game_root, "mods", "bf2", "Levels")
    if not os.path.isdir(levels_dir):
        return
    for name in sorted(os.listdir(levels_dir)):
        server_zip = os.path.join(levels_dir, name, "server.zip")
        if os.path.isfile(server_zip):
            yield name.lower(), server_zip


def _extract_level(server_zip: str) -> dict:
    result: dict = {}
    with zipfile.ZipFile(server_zip) as zf:
        for entry in zf.namelist():
            if not entry.endswith("GamePlayObjects.con"):
                continue
            # e.g. GameModes/gpm_cq/32/GamePlayObjects.con
            parts = entry.replace("\\", "/").split("/")
            if len(parts) < 3:
                continue
            mode = parts[-3]
            size = parts[-2]
            parsed = _parse_con(zf.read(entry).decode("latin1"))
            control_points = []
            for obj in parsed["placed"]:
                tmpl = parsed["templates"].get(obj["name"])
                if tmpl and tmpl.get("type") == "ControlPoint":
                    control_points.append({
                        "id": tmpl.get("control_point_id"),
                        "team": tmpl.get("team", 0),
                        "name": obj["name"],
                    })
            spawners = []
            for o in parsed["placed"]:
                tmpl = parsed["templates"].get(o["name"])
                if tmpl and tmpl.get("type") == "ObjectSpawner":
                    spawners.append({
                        "name": o["name"],
                        "spawn_vehicles": tmpl.get("spawn_vehicles", {}),
                    })
            result.setdefault(mode, {})[size] = {
                "control_points": control_points,
                "spawners": spawners,
            }
    return result


def _extract_localization(game_root: str) -> dict:
    names: dict = {}
    roots = [
        os.path.join(game_root, "mods", "bf2", "Localization", "english"),
        os.path.join(game_root, "mods", "xpack", "Localization", "english"),
    ]
    files = []
    for root in roots:
        if os.path.isdir(root):
            files.extend(
                os.path.join(root, f) for f in sorted(os.listdir(root)) if f.endswith(".utxt")
            )
    for path in files:
        if not os.path.isfile(path):
            continue
        text = open(path, "rb").read().decode("utf-16-le", "replace")
        for line in text.splitlines():
            # Control characters (0x1b etc.) separate key and value in some files.
            line = "".join(" " if ord(ch) < 32 else ch for ch in line)
            line = " ".join(line.split())
            if not line:
                continue
            key, _, value = line.partition(" ")
            value = value.replace("\u00a7C1001", "").replace("\uf8ff", "").strip()
            for prefix in ("KILLMESSAGE_VEHICLE_", "KILLMESSAGE_WEAPON_"):
                if key.startswith(prefix):
                    names[key[len(prefix):]] = value
    # Immutable template aliases: the stationary bipod templates reuse the
    # mounted-machinegun localisation strings verbatim.
    for alias, source in (("us_bipod", "stationarym249"),
                          ("mec_bipod", "stationaryrpk74"),
                          ("ch_bipod", "hmgtype95")):
        if names.get(source):
            names[alias] = names[source]
    return names


def main() -> int:
    game_root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GAME
    out_path = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT)
    levels = {}
    for level, server_zip in _iter_level_archives(game_root):
        levels[level] = _extract_level(server_zip)
    assets = {
        "version": 2,
        "source_build": "1.5.3153.0",
        "levels": levels,
        "localization": _extract_localization(game_root),
        "vehicle_categories": VEHICLE_CATEGORIES,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(assets, fh, separators=(",", ":"), sort_keys=True)
    print(f"wrote {out_path} ({os.path.getsize(out_path)} bytes), {len(levels)} levels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
