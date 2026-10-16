"""Validation aid: compare demo-decoded vehicles with a level's GamePlayObjects.con.

The level ``server.zip`` is a *reference for testing only*; the parser never
reads it. For every vehicle created in the demo this prints the ObjectSpawner
that declares that vehicle template and the exact position/rotation deltas.

Usage::

    python scripts/validate_gpo.py DEMO [server.zip] [mode/size]
"""

from __future__ import annotations

import math
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bf2demo.reader import load_demo  # noqa: E402
from bf2demo.replay import build_replay  # noqa: E402

GAME_LEVELS = r"C:\Program Files (x86)\EA Games\Battlefield 2\mods\bf2\Levels"


def parse_gpo(text: str):
    """Return (spawner templates, spawner instances, control point instances)."""
    templates, instances, cps = {}, [], []
    current = None
    obj = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"ObjectTemplate\.create\s+(\w+)\s+(\S+)", line, re.I)
        if m:
            current = {"class": m.group(1), "name": m.group(2), "vehicles": {}, "props": {}}
            templates[m.group(2).lower()] = current
            continue
        m = re.match(r"ObjectTemplate\.setObjectTemplate\s+(\d+)\s+(\S+)", line, re.I)
        if m and current:
            current["vehicles"][int(m.group(1))] = m.group(2)
            continue
        m = re.match(r"ObjectTemplate\.(\w+)\s+(.*)", line, re.I)
        if m and current:
            current["props"][m.group(1)] = m.group(2)
            continue
        m = re.match(r"Object\.create\s+(\S+)", line, re.I)
        if m:
            obj = {"name": m.group(1), "pos": None, "rot": (0.0, 0.0, 0.0), "props": {}}
            instances.append(obj)
            continue
        m = re.match(r"Object\.(\w+)\s+(.*)", line, re.I)
        if m and obj:
            key, val = m.group(1), m.group(2)
            if key.lower() == "absoluteposition":
                obj["pos"] = tuple(float(v) for v in val.split("/"))
            elif key.lower() == "rotation":
                obj["rot"] = tuple(float(v) for v in val.split("/"))
            else:
                obj["props"][key] = val
    for inst in instances:
        tpl = templates.get(inst["name"].lower())
        inst["template"] = tpl
        if tpl and tpl["class"].lower() == "controlpoint":
            cps.append(inst)
    spawners = [i for i in instances if i["template"] and i["template"]["class"].lower() == "objectspawner"]
    return spawners, cps


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    replay = build_replay(load_demo(argv[0]))
    level = replay.demo.header.map_name
    zpath = argv[1] if len(argv) > 1 else None
    if not zpath:
        for entry in os.listdir(GAME_LEVELS):
            if entry.lower() == level.lower():
                zpath = os.path.join(GAME_LEVELS, entry, "server.zip")
    layer = argv[2] if len(argv) > 2 else replay.templates.layer
    zf = zipfile.ZipFile(zpath)
    names = {n.lower(): n for n in zf.namelist()}
    text = zf.read(names[f"gamemodes/{layer}/gameplayobjects.con".lower()]).decode("latin1")
    spawners, cps = parse_gpo(text)
    print(f"{level} {layer}: {len(spawners)} spawners, {len(cps)} control points in GamePlayObjects.con")

    print("\nCONTROL POINTS (demo vs .con):")
    for cp in replay.control_points.values():
        ref = next((c for c in cps if c["name"].lower() == cp.template.name.lower()), None)
        if ref is None:
            print(f"  {cp.template.name}: not in .con")
            continue
        d = _dist(cp.position, ref["pos"])
        print(f"  {cp.template.name:<38} demo={cp.position} con={ref['pos']} d={d:.4f}")

    print("\nVEHICLES (first creation of each object vs nearest spawner declaring that template):")
    worst = 0.0
    matched = unmatched = 0
    used = {}
    for obj in replay.object_history:
        if not obj.template.is_vehicle or obj.position is None:
            continue
        name = obj.template.name.lower()
        cands = [s for s in spawners if name in {v.lower() for v in s["template"]["vehicles"].values()}]
        if not cands:
            unmatched += 1
            print(f"  {obj.template.name:<22} pos={obj.position}  NO SPAWNER declares this template")
            continue
        s = min(cands, key=lambda s: _dist(s["pos"], obj.position))
        d = _dist(s["pos"], obj.position)
        rot = obj.rotation or (0.0, 0.0, 0.0)
        used.setdefault(s["name"], []).append(d)
        if obj.object_id in {o for o in []}:
            pass
        worst = max(worst, d)
        matched += 1
        print(f"  {obj.template.name:<22} tick={obj.created_tick:<6} d={d:9.4f}  "
              f"demo=({obj.position[0]:.3f}/{obj.position[1]:.3f}/{obj.position[2]:.3f}) "
              f"con={s['pos'][0]:.3f}/{s['pos'][1]:.3f}/{s['pos'][2]:.3f}  "
              f"rot demo={rot[0]:.3f} con={s['rot'][0]:.3f}  {s['name']}")
    print(f"\nmatched={matched} unmatched={unmatched} worst_distance={worst:.4f}")
    never = [s["name"] for s in spawners if s["name"] not in used]
    print(f"spawners without a vehicle in this demo: {len(never)}")

    print("\nRECONSTRUCTED SPAWNERS vs .con (exact sites must match a spawner transform to 0.001):")
    ok = bad = 0
    recovered = set()
    for site in replay.spawn_sites:
        if not site.exact:
            continue
        hit = None
        for s in spawners:
            if s["pos"] and max(abs(a - b) for a, b in zip(s["pos"], site.position)) <= 0.0015 \
                    and abs(((s["rot"][0] - site.rotation[0]) + 180) % 360 - 180) <= 0.0015:
                hit = s
                break
        names = set(site.templates) | set(site.snapshot_templates)
        declared = {v.lower() for v in hit["template"]["vehicles"].values()} if hit else set()
        if hit and all(n.lower() in declared for n in names):
            ok += 1
            recovered.add(hit["name"])
        else:
            bad += 1
            where = hit["name"] if hit else "no spawner here"
            print(f"  MISMATCH {'/'.join(f'{c:.3f}' for c in site.position)} {sorted(names)} "
                  f"confirmed={site.confirmed} -> {where}")
    print(f"exact sites matching a declared spawner: {ok}/{ok + bad}; "
          f"spawners recovered exactly: {len(recovered)}/{len(spawners)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
