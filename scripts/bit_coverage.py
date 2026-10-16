"""How many bits of a demo are understood? (thin wrapper around ``bf2demo.coverage``)

Usage: python scripts/bit_coverage.py [--list] DEMO [DEMO ...]

``--list`` prints every ghost body that no decoder explained exactly. The exit status is 1 when any body is unexplained.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bf2demo.coverage import analyse, format_report  # noqa: E402
from bf2demo.reader import load_demo  # noqa: E402
from bf2demo.replay import build_replay  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("demos", nargs="+")
    parser.add_argument("--list", action="store_true", help="list the undecoded ghost bodies")
    args = parser.parse_args(argv)
    incomplete = False
    for path in args.demos:
        replay = build_replay(load_demo(path))
        report = analyse(replay)
        print(format_report(os.path.basename(path), replay, report))
        if args.list:
            for ghost_id, tick, bits, kind in report.undecoded_records:
                print(f"   undecoded ghost {ghost_id} tick {tick} bits {bits}  {kind}")
        incomplete |= not report.complete
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
