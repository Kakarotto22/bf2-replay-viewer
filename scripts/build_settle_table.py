"""Development tool: learn how far a mobile vehicle settles from its spawn position.

The join snapshot sends a vehicle's *current* position, i.e. after the physics engine rested
it on the ground (``ServerConnection::clientSendDatabase`` uses the live position). The
original spawner Y is therefore not transmitted for vehicles that exist when a recording
starts. For ground vehicles the rest height above the spawn position is the same for every
spawner of a template, so it can be learned once and subtracted.

For every demo with a bundled retail layout, each snapshot vehicle is matched to the layout
spawner that declares its template and sits at the same X/Z; the Y difference is collected.
Per template the median is stored together with the 90th percentile of the deviations from it (``spread``, metres:
ground slope makes spawners of one template differ by a few centimetres) and the share within 1 cm (``coherence``). Aircraft spawn on the ground or on the carrier deck and are not coherent.

Usage: python scripts/build_settle_table.py [demo ...] [DEMO=GamePlayObjects.con ...]   (default: samples/*.bf2demo)
"""

from __future__ import annotations

import collections
import glob
import json
import math
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bf2demo.layouts import layout_text, parse_layout  # noqa: E402
from bf2demo.reader import load_demo  # noqa: E402
from bf2demo.replay import build_replay  # noqa: E402

XZ_LIMIT = 0.6
MAX_JOIN_TICK = 60        # only recordings made from map load (auto-record): vehicles untouched, short files


def _spawners(text):
    """``[(absolutePosition, {vehicle templates})]`` of a GamePlayObjects.con."""
    items = parse_layout(text)
    templates = {i.name.lower(): i for i in items if i.is_block and i.is_template and i.cls == "objectspawner"}
    spawners = []
    for item in items:
        if item.is_block and not item.is_template and item.cls == "objectspawner":
            tpl = templates.get(item.name.lower())
            slots = set()
            for line in (tpl.lines if tpl else []):
                m = re.match(r"\s*ObjectTemplate\.setObjectTemplate\s+\d+\s+(\S+)", line, re.I)
                if m:
                    slots.add(m.group(1).lower())
            spawners.append((item.vec("absolutePosition"), slots))
    return spawners


def collect(sources):
    """``{template: [settled Y - spawner Y]}`` from ``(demo path, GamePlayObjects.con text, latest first tick)`` triples."""
    rows = collections.defaultdict(list)
    for path, text, max_join in sources:
        replay = build_replay(load_demo(path))
        if not replay.object_history or replay.object_history[0].created_tick > max_join:
            continue
        spawners = _spawners(text)
        for obj in replay.object_history:
            if not obj.snapshot or not obj.template.is_vehicle or obj.template.mobile is not True or not obj.position:
                continue
            near = [s for s in spawners if obj.template.name.lower() in s[1]
                    and math.hypot(s[0][0] - obj.position[0], s[0][2] - obj.position[2]) < XZ_LIMIT]
            if len(near) == 1:            # two candidates within reach (stacked spawners) would make the pairing a guess
                rows[obj.template.name.lower()].append(round(obj.position[1] - near[0][0][1], 3))
    return rows


def retail_sources(paths):
    """Recordings made at map load on unmodified retail maps, with the bundled retail layout as the truth."""
    for path in paths:
        replay = build_replay(load_demo(path))
        text = layout_text(replay.level, replay.game_mode, replay.map_size)
        if text:
            yield path, text, MAX_JOIN_TICK


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    truth = [a.split("=", 1) for a in argv if "=" in a]          # DEMO=GamePlayObjects.con of the map the demo was recorded on
    paths = [a for a in argv if "=" not in a] or sorted(glob.glob(os.path.join(ROOT, "samples", "*.bf2demo")))
    sources = list(retail_sources(paths))
    for demo, con in truth:           # a customised map whose real spawner coordinates are known (no players: vehicles untouched)
        with open(con, encoding="latin1") as fh:
            sources.append((demo, fh.read(), 900))
    rows = collect(sources)
    table = {}
    for name, values in sorted(rows.items()):
        median = statistics.median(values)
        deviations = sorted(abs(v - median) for v in values)
        coherence = sum(1 for v in values if abs(v - median) <= 0.01) / len(values)
        table[name] = {"dy": round(median, 3), "n": len(values), "coherence": round(coherence, 2),
                       "spread": round(deviations[min(len(deviations) - 1, int(0.9 * len(deviations)))], 3)}
    out = os.path.join(ROOT, "bf2demo", "assets", "settle_offsets.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"doc": "settled Y minus spawner Y per mobile vehicle template (see scripts/build_settle_table.py)",
                   "templates": table}, fh, indent=1)
    from bf2demo.settle import settle_offset
    usable = [n for n in table if settle_offset(n) is not None]
    print(f"{len(table)} templates, {len(usable)} usable (n>=3, 90% of the spawners within 0.10 m of the median): "
          + ", ".join(usable))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
