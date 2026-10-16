"""One-time extractor: bundle the retail ``GamePlayObjects.con`` files as layouts.

The exporter (:mod:`bf2demo.export_con`) needs the *static text* of a level's
``GamePlayObjects.con`` (object names, order, per-team vehicle templates, spawn
delays, author, control point ids, ``CombatArea``...) because none of it crosses
the wire. This script copies every ``GameModes/<mode>/<size>/GamePlayObjects.con``
from the level ``server.zip`` archives into ``bf2demo/assets/layouts.json.gz``.
It is a development tool: the parser itself never opens game files.

Usage::

    python scripts/build_layouts.py [mods/bf2 root] [output]
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import zipfile


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    root = argv[0] if argv else r"C:\Program Files (x86)\EA Games\Battlefield 2\mods\bf2"
    out_path = argv[1] if len(argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bf2demo", "assets", "layouts.json.gz")
    levels_dir = next(os.path.join(root, d) for d in os.listdir(root) if d.lower() == "levels")
    layouts = {}
    count = 0
    for level in sorted(os.listdir(levels_dir)):
        zpath = None
        for entry in os.listdir(os.path.join(levels_dir, level)):
            if entry.lower() == "server.zip":
                zpath = os.path.join(levels_dir, level, entry)
        if not zpath:
            continue
        zf = zipfile.ZipFile(zpath)
        for name in zf.namelist():
            parts = name.replace("\\", "/").split("/")
            if len(parts) == 4 and parts[0].lower() == "gamemodes" and parts[3].lower() == "gameplayobjects.con":
                text = zf.read(name).decode("latin1").replace("\r\n", "\n")
                layouts.setdefault(level.lower(), {})[f"{parts[1].lower()}/{parts[2]}"] = text
                count += 1
    with gzip.open(out_path, "wt", encoding="latin1", compresslevel=9) as fh:
        json.dump({"source": "retail 1.5.3153 level server.zip GamePlayObjects.con (LF-normalised)",
                   "layouts": layouts}, fh, separators=(",", ":"))
    print(f"{count} layouts for {len(layouts)} levels -> {out_path} ({os.path.getsize(out_path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
