"""Build a level ``server.zip`` that spawns every PlayerControlObject root template (validation demo).

The ghost body of an object is derived from its template tree (``scripts/netseq.py``). To validate that rule for every vehicle
the demo must contain one of each, but the retail maps only use a handful. ``object.create`` at run time fails (the collision
mesh is not loaded), so this script adds one ``ObjectSpawner`` per template to the level's ``GamePlayObjects.con`` before load.

Examples (original archives are kept as ``server.zip.bak``; restore them afterwards)::

    # base game, Dalian Plant
    python scripts/make_vehicle_test_zip.py .../Dalian_Plant/server.zip.bak .../Dalian_Plant/server.zip
    # Special Forces, Surge (its control point ids are 101/102)
    python scripts/make_vehicle_test_zip.py .../xpack/Levels/Surge/server.zip.bak .../Surge/server.zip \\
        --xpack-root ".../mods/xpack" --control-point 101
    # booster pack levels
    python scripts/make_vehicle_test_zip.py SRC DST --booster --control-point <id>

Record with ``sv.autoRecord 1`` (the demo starts at map load) and end the round with ``admin.runNextLevel`` after about a minute.
The template ``bipod`` (abstract base of the bipod weapons) crashes the server while loading and is skipped.
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_templates  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_PLAY_OBJECTS = "GameModes/gpm_cq/16/GamePlayObjects.con"
SKIP = {"dummy", "bipod"}
GRID_COLUMNS = 9
GRID_SPACING = 30.0
GRID_ORIGIN = -420.0
SPAWN_HEIGHT = 170.0
DEFAULT_CONTROL_POINT_ID = 401          # a Dalian control point; the spawner takes its team from it


def vehicle_roots(mod_root: str, overlay_root=None, booster: bool = False):
    """Names of the PlayerControlObject templates that are not nested inside another template."""
    registry = build_templates.build_global(mod_root, booster=booster, overlay_root=overlay_root)
    nested = {child for kids in registry.children.values() for child in kids}
    return sorted(name for name, cls in registry.classes.items()
                  if cls.lower() == "playercontrolobject" and name not in nested and name not in SKIP)


def spawner_templates(names) -> str:
    return "".join(
        f"rem [ObjectSpawnerTemplate: TESTSP_{n}]\nObjectTemplate.create ObjectSpawner TESTSP_{n}\n"
        f"ObjectTemplate.activeSafe ObjectSpawner TESTSP_{n}\nObjectTemplate.modifiedByUser \"bf2demo\"\n"
        f"ObjectTemplate.isNotSaveable 1\nObjectTemplate.hasMobilePhysics 0\n"
        f"ObjectTemplate.setObjectTemplate 1 {n}\nObjectTemplate.setObjectTemplate 2 {n}\n\n" for n in names)


def spawner_instances(names, control_point_id: int) -> str:
    out = []
    for index, name in enumerate(names):
        x = GRID_ORIGIN + (index % GRID_COLUMNS) * GRID_SPACING
        z = GRID_ORIGIN + (index // GRID_COLUMNS) * GRID_SPACING
        out.append(f"   rem [ObjectSpawner: TESTSP_{name}]\n   Object.create TESTSP_{name}\n"
                   f"   Object.absolutePosition {x:.3f}/{SPAWN_HEIGHT:.3f}/{z:.3f}\n   Object.rotation 0.000/0.000/0.000\n"
                   f"   Object.setControlPointId {control_point_id}\n   Object.layer 5\n\n")
    return "".join(out)


def build(src: str, dst: str, names, control_point_id: int = DEFAULT_CONTROL_POINT_ID) -> None:
    with zipfile.ZipFile(src) as zin:
        text = zin.read(GAME_PLAY_OBJECTS).decode("latin1").replace("\r\n", "\n")
        marker = "rem ********** Object Spawner **********\n"
        host_block = "if v_arg1 == host\n\n"
        if marker not in text or host_block not in text:
            raise SystemExit("unexpected GamePlayObjects.con layout")
        text = text.replace(marker, marker + spawner_templates(names), 1)
        text = text.replace(host_block, host_block + spawner_instances(names, control_point_id), 1)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = text.replace("\n", "\r\n").encode("latin1") if item.filename == GAME_PLAY_OBJECTS else zin.read(item.filename)
                zout.writestr(item, data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("src", help="original level server.zip (kept as server.zip.bak)")
    parser.add_argument("dst", help="patched server.zip to write")
    parser.add_argument("--mod-root", default=os.path.join(REPO, "re_work", "server", "root", "mods", "bf2"),
                        help="extracted mods/bf2 folder used to read the template tree")
    parser.add_argument("--xpack-root", help="mods/xpack folder (Special Forces vehicles)")
    parser.add_argument("--booster", action="store_true", help="include the booster pack templates")
    parser.add_argument("--control-point", type=int, default=DEFAULT_CONTROL_POINT_ID,
                        help="control point id of the level that owns the spawners")
    args = parser.parse_args(argv)
    names = vehicle_roots(args.mod_root, args.xpack_root, args.booster)
    build(args.src, args.dst, names, args.control_point)
    print(f"wrote {args.dst} with {len(names)} spawners")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
