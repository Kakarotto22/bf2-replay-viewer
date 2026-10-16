"""Development probe: how much of each ghost update does a candidate decoder sequence explain?

For every ghost update of objects of the given template classes, run SimpleObjectNetworkable and report the
distribution of the *remaining* bits (0 = the record is explained completely) per first-mask value.

Usage: python scripts/ghost_probe.py DEMO CLASS [CLASS ...]
"""

from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bf2demo.bitstream import BitStream  # noqa: E402
from bf2demo.ghostbits import width_for  # noqa: E402
from bf2demo.objectnet import SimpleObjectContext, UnsupportedLayout, decode_simple_object  # noqa: E402
from bf2demo.packet import GHOST_UPDATE, PacketError, parse_packet  # noqa: E402
from bf2demo.reader import load_demo  # noqa: E402
from bf2demo.replay import build_replay  # noqa: E402


def main(path, classes):
    demo = load_demo(path)
    replay = build_replay(demo)
    by_id = {}
    for obj in replay.object_history:
        by_id.setdefault(obj.object_id, []).append(obj)

    def find(oid, tick):
        for o in reversed(by_id.get(oid, [])):
            if o.created_tick <= tick and (o.destroyed_tick is None or o.destroyed_tick >= tick):
                return o
        return None

    stats = {c: collections.defaultdict(collections.Counter) for c in classes}
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
            obj = find(g.ghost_id, packet.tick)
            if obj is None or obj.template is None or obj.template.cls not in stats:
                continue
            t = obj.template
            range_bits = t.range_bits
            ctx = SimpleObjectContext(has_physics=bool(obj.template.mobile), range_bits=range_bits,
                                      is_player_control=obj.template.cls in ("PlayerControlObject", "Parachute"),
                                      is_parachute=obj.template.cls == "Parachute")
            bs = BitStream(packet.data, g.bit_start)
            try:
                upd = decode_simple_object(bs, ctx)
            except UnsupportedLayout:
                stats[obj.template.cls]["needs range"][0] += 1
                continue
            stats[obj.template.cls][hex(upd.mask)][g.bit_length - upd.bits] += 1
    for cls, table in stats.items():
        print(cls)
        for mask, rem in sorted(table.items(), key=lambda kv: -sum(kv[1].values()))[:10]:
            print(f"   mask {mask:>8}: {sum(rem.values()):7d} records, remaining bits {rem.most_common(4)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])


def range_width_search(path, cls):
    """For records with mask bit 0x10: which width makes the SimpleObject explain the whole record?"""
    demo = load_demo(path)
    replay = build_replay(demo)
    by_id = {}
    for obj in replay.object_history:
        by_id.setdefault(obj.object_id, []).append(obj)
    best = collections.defaultdict(collections.Counter)
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
            obj = next((o for o in reversed(by_id.get(g.ghost_id, []))
                        if o.created_tick <= packet.tick and (o.destroyed_tick is None or o.destroyed_tick >= packet.tick)), None)
            if obj is None or obj.template is None or obj.template.cls != cls:
                continue
            if not (BitStream(packet.data, g.bit_start).read_bits(19) & 0x10):
                continue
            for width in range(0, 33):
                ctx = SimpleObjectContext(has_physics=bool(obj.template.mobile), range_bits=width,
                                          is_player_control=cls in ("PlayerControlObject", "Parachute"),
                                          is_parachute=cls == "Parachute")
                upd = decode_simple_object(BitStream(packet.data, g.bit_start), ctx)
                if upd.bits == g.bit_length:
                    best[obj.template.name][width] += 1
    for name, counter in best.items():
        print(cls, name, counter.most_common(4))
