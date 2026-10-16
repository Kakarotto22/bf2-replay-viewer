"""Development probe: how exactly do the template-derived networkable sequences explain vehicle ghost records?

For every PlayerControlObject template seen in the demos: decode SimpleObject + the bundled sequence
(`TemplateInfo.netseq`, `objectnet.decode_vehicle`) and report the exactness per template.

Usage: python scripts/vehicle_probe.py DEMO [DEMO ...]
"""

from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bf2demo.bitstream import BitStream  # noqa: E402
from bf2demo.objectnet import decode_vehicle  # noqa: E402
from bf2demo.packet import GHOST_UPDATE, PacketError, parse_packet  # noqa: E402
from bf2demo.reader import load_demo  # noqa: E402
from bf2demo.replay import build_replay  # noqa: E402


def main(paths):
    stats = collections.defaultdict(lambda: [0, 0])      # template -> [exact, total]
    for path in paths:
        demo = load_demo(path)
        replay = build_replay(demo)
        by_id = {}
        for obj in replay.object_history:
            by_id.setdefault(obj.object_id, []).append(obj)
        for packet in demo.packets:
            if not packet.data or packet.tick < 0:
                continue
            try:
                pkt = parse_packet(packet.data)
            except PacketError:
                continue
            for g in pkt.ghosts:
                if g.action != GHOST_UPDATE:
                    continue
                obj = next((o for o in reversed(by_id.get(g.ghost_id, [])) if o.created_tick <= packet.tick
                            and (o.destroyed_tick is None or o.destroyed_tick >= packet.tick)), None)
                if obj is None or obj.template is None or not obj.template.netseq:
                    continue
                try:
                    ok = decode_vehicle(BitStream(packet.data, g.bit_start), obj.template) == g.bit_length
                except Exception:
                    ok = False
                cell = stats[obj.template.name]
                cell[1] += 1
                cell[0] += ok
    for name, (ok, total) in sorted(stats.items(), key=lambda kv: -kv[1][1]):
        print(f"{name:28} {total:7d} records  exact {ok / total:7.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
