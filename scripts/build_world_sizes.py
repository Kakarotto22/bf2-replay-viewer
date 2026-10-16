"""Extract the world size of every level into ``bf2demo/assets/world_sizes.json``.

``GLSWorldSizeX/Z`` (``GameLogic::loadInitFile`` 0x080d36b0) is the size of the level's heightmap cluster, i.e. the value of
``heightmapcluster.setHeightmapSize`` in the level's ``Heightdata.con``. A ``SpawnGroup`` sends its position as two bytes,
``byte = int((size / 2 + coordinate) / size * 255)`` (``getUnsignedWorldPosition`` 0x08111840), so the size is needed to read them.

Usage::

    python scripts/build_world_sizes.py MODS_ROOT [OUT.json]

``MODS_ROOT`` is the folder that holds ``bf2`` and ``xpack`` (the dedicated server's ``mods`` folder).
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile

_SIZE = re.compile(r"heightmapcluster\.setHeightmapSize\s+(\d+)", re.I)


def level_sizes(mods_root: str):
    sizes = {}
    for mod in ("bf2", "xpack"):
        levels = os.path.join(mods_root, mod, "Levels")
        if not os.path.isdir(levels):
            continue
        for level in sorted(os.listdir(levels)):
            archive = os.path.join(levels, level, "server.zip")
            if not os.path.isfile(archive):
                continue
            with zipfile.ZipFile(archive) as zf:
                names = {n.lower(): n for n in zf.namelist()}
                if "heightdata.con" not in names:
                    continue
                match = _SIZE.search(zf.read(names["heightdata.con"]).decode("latin1"))
                if match:
                    sizes[level.lower()] = int(match.group(1))
    return sizes


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    out = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                    "bf2demo", "assets", "world_sizes.json")
    sizes = level_sizes(argv[0])
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"doc": "level -> GLSWorldSize (heightmapcluster.setHeightmapSize of Heightdata.con)", "sizes": sizes},
                  fh, indent=0, sort_keys=True)
    print(f"{len(sizes)} levels -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
