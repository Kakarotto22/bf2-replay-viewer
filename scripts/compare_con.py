"""Compare a reconstructed GamePlayObjects.con with a reference one.

Both files are parsed into (class, template props, instance transform). The
comparison is semantic, not textual: names of reconstructed spawners are
synthetic, so objects are matched by transform.

Usage::

    python scripts/compare_con.py GENERATED.con REFERENCE.con [--tol 0.0015]
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bf2demo.conparse import parse  # noqa: E402,F401


def _yaw_delta(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _spawn_pos(inst: dict) -> tuple:
    off = inst["tpl"]["props"].get("setspawnpositionoffset") if inst["tpl"] else None
    o = tuple(float(v) for v in off.split("/")) if off else (0.0, 0.0, 0.0)
    return tuple(p + d for p, d in zip(inst["pos"], o))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("generated")
    ap.add_argument("reference")
    ap.add_argument("--tol", type=float, default=0.0015)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    gen = parse(open(args.generated, encoding="latin1").read())
    ref = parse(open(args.reference, encoding="latin1").read())
    tol = args.tol
    bad = 0

    print("CONTROL POINTS")
    for r in ref["controlpoint"]:
        g = next((x for x in gen["controlpoint"] if x["name"].lower() == r["name"].lower()), None)
        if g is None:
            print(f"  MISSING {r['name']}")
            bad += 1
            continue
        d = math.dist(g["pos"], r["pos"])
        team_ok = g["tpl"]["props"].get("team", "0") == r["tpl"]["props"].get("team", "0")
        status = "ok" if d <= tol and team_ok else "DIFF"
        bad += status != "ok"
        print(f"  {status:<4} {r['name']:<36} d={d:.4f} team gen={g['tpl']['props'].get('team', '0')} "
              f"ref={r['tpl']['props'].get('team', '0')}")

    print("OBJECT SPAWNERS (matched by transform)")
    used = set()
    exact = approx = missing = 0
    slot_ok = slot_total = 0
    for r in ref["objectspawner"]:
        cands = [g for g in gen["objectspawner"] if id(g) not in used]
        near = min(cands, key=lambda g: math.dist(g["pos"], r["pos"]), default=None)
        if near is None:
            missing += 1
            if args.verbose:
                print(f"  not recovered: {r['name']} {r['pos']} {sorted(r['tpl']['slots'].values())}")
            continue
        d = math.dist(near["pos"], r["pos"])
        if d > 3.0:
            missing += 1
            if args.verbose:
                print(f"  not recovered: {r['name']} {r['pos']} {sorted(r['tpl']['slots'].values())}")
            continue
        used.add(id(near))
        yaw = _yaw_delta(near["rot"][0], r["rot"][0])
        if d <= tol and yaw <= tol:
            exact += 1
        else:
            approx += 1
            if args.verbose:
                print(f"  approx d={d:.3f} yaw={yaw:.3f} {r['name']} <- {near['name']}")
        for slot, tpl in near["tpl"]["slots"].items():
            slot_total += 1
            if r["tpl"]["slots"].get(slot) == tpl:
                slot_ok += 1
            else:
                bad += 1
                print(f"  SLOT MISMATCH {r['name']} slot {slot}: gen={tpl} ref={r['tpl']['slots'].get(slot)}")
    extra = [g for g in gen["objectspawner"] if id(g) not in used]
    for g in extra:
        print(f"  EXTRA (not in reference) {g['name']} {g['pos']} {sorted(g['tpl']['slots'].values())}")
    print(f"  reference spawners={len(ref['objectspawner'])} exact={exact} approx={approx} "
          f"not_recovered={missing} extra={len(extra)}; team slots correct {slot_ok}/{slot_total}")

    print("SPAWN POINTS (final spawn position = absolutePosition + offset)")
    ref_pts = ref["spawnpoint"]
    hit = 0
    dys = []
    for g in gen["spawnpoint"]:
        gp = _spawn_pos(g)
        near = min(ref_pts, key=lambda r: math.hypot(r["pos"][0] - gp[0], r["pos"][2] - gp[2]), default=None)
        if near is None:
            continue
        dxz = math.hypot(near["pos"][0] - gp[0], near["pos"][2] - gp[2])
        if dxz <= tol:
            hit += 1
            dys.append(round(gp[1] - near["pos"][1], 3))
        else:
            print(f"  EXTRA spawn point {g['name']} {gp} nearest ref {dxz:.2f} m")
    print(f"  generated={len(gen['spawnpoint'])} reference={len(ref_pts)} XZ-exact={hit}; "
          f"Y minus reference Y: {sorted(set(dys))}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
