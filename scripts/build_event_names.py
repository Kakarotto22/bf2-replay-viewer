"""Development tool: rebuild ``bf2demo/assets/event_names.json`` from BF2.exe decompiles.

The client registers every EventManager event with an explicit id and name::

    python scripts/decomp.py --program BF2.exe re_work/decomp/reg_hud.c 0x0074e090   # HUD events (category 2)
    python scripts/decomp.py --program BF2.exe re_work/decomp/reg_net.c 0x00442d90 0x004f6690
    python scripts/build_event_names.py re_work/decomp/reg_hud.c re_work/decomp/reg_net.c

The decompiled code reads ``basic_string(local_20,"ECHudHEName"); registerEvent(category, id, local_20)``.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = {"0": "ECGameLogicGL", "1": "ECGameGN", "2": "ECHudHE", "6": "ECNetworkNE"}
CATEGORIES = {"0": "GameLogic", "1": "Game", "2": "Hud", "6": "Network"}
PATTERN = re.compile(r'"(EC\w+)"|\((\d+|0x[0-9a-f]+),(0x[0-9a-f]+|\d+),local_')


def main(paths) -> int:
    events = {c: {} for c in CATEGORIES}
    for path in paths:
        text = open(path, encoding="utf-8", errors="replace").read()
        for block in text.split("==== ")[1:]:
            name = None
            for m in PATTERN.finditer(block):
                if m.group(1):
                    name = m.group(1)
                    continue
                category, event_id = str(int(m.group(2), 0)), str(int(m.group(3), 0))
                if category in events and name:
                    prefix = PREFIX[category]
                    events[category][event_id] = name[len(prefix):] if name.startswith(prefix) else name
    doc = {"doc": "EventManager (category, id) -> name, from the registerEvent calls in BF2.exe; "
                  "PostRemoteEvent carries (category, id)",
           "categories": CATEGORIES, "events": events}
    out = os.path.join(ROOT, "bf2demo", "assets", "event_names.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=0)
    print(f"{sum(len(v) for v in events.values())} events -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
