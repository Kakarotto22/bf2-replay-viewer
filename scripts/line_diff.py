"""Line-level comparison of a reconstructed .con with a reference (body only).

Usage: python scripts/line_diff.py GENERATED.con REFERENCE.con [--show N]
Ours is compared up to the parser-notes block; the reference is compared whole.
"""

from __future__ import annotations

import argparse
import difflib


def body(path: str, stop: str):
    with open(path, "r", encoding="latin1", newline="") as fh:
        lines = fh.read().split("\r\n")
    for i, line in enumerate(lines):
        if line.startswith(stop):
            return lines[:i]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("generated")
    ap.add_argument("reference")
    ap.add_argument("--show", type=int, default=0, help="print the first N differing hunks")
    args = ap.parse_args()
    ours = body(args.generated, "rem ********** bf2demo parser notes")
    ref = body(args.reference, "@@no-such-line@@")
    sm = difflib.SequenceMatcher(None, ref, ours, autojunk=False)
    same = sum(i2 - i1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal")
    print(f"reference body lines={len(ref)} generated body lines={len(ours)} identical={same} "
          f"({same / max(1, len(ref)):.0%} of reference)")
    shown = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or shown >= args.show:
            continue
        shown += 1
        print(f"--- {tag} ref[{i1}:{i2}] gen[{j1}:{j2}]")
        for line in ref[i1:i2][:8]:
            print(f"- {line}")
        for line in ours[j1:j2][:8]:
            print(f"+ {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
