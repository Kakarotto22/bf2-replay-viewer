"""Write ``.bf2demo`` files: an unchanged copy, a recording cut short at a tick, or a clip that starts at a later tick.

Container (see :mod:`bf2demo.reader`): a Zlib stream of an int32 engine version, three length-prefixed latin-1 strings (server name, recording
time, map) and then packets ``<ii`` = (tick, payload length) + payload.

* **End cut** (``end_tick``): every packet up to the tick, untouched - always a valid recording of the first part of the round.
* **Start cut** (``start_tick``, EXPERIMENTAL, untested in the game): ghost updates are deltas, so a recording cannot simply begin in the middle;
  the packets before the clip stay, but the header ticks of those between the round start and ``start_tick - lead`` are rewritten to one tick so
  that the game can apply them at once instead of replaying them in real time. Negative-tick packets (join, data blocks, snapshot) and
  every payload are left exactly as recorded, and packets of the clip keep their own ticks (absolute ticks inside payloads stay valid).
"""

from __future__ import annotations

import struct
import zlib
from typing import List, Optional

from .models import Demo, DemoPacket
from .reader import load_demo

TICKS_PER_SECOND = 30


def _lpstring(text: str) -> bytes:
    raw = text.encode("latin1")
    return struct.pack("<i", len(raw)) + raw


def serialize(demo: Demo, packets: Optional[List[DemoPacket]] = None, ticks: Optional[List[int]] = None) -> bytes:
    """The inflated stream of ``demo`` (``packets`` / ``ticks`` replace the packet list / the header ticks when given)."""
    h = demo.header
    out = bytearray(struct.pack("<i", h.version))
    out += _lpstring(h.server_name) + _lpstring(h.recorded_at) + _lpstring(h.map_name)
    packets = demo.packets if packets is None else packets
    for i, packet in enumerate(packets):
        tick = packet.tick if ticks is None else ticks[i]
        out += struct.pack("<ii", tick, len(packet.data)) + packet.data
    return bytes(out)


def compress(stream: bytes, level: int = 6) -> bytes:
    return zlib.compress(stream, level)


def make_clip(demo: Demo, start_tick: Optional[int] = None, end_tick: Optional[int] = None, lead_seconds: float = 8.0,
              signature: bool = False) -> bytes:
    """The ``.bf2demo`` bytes of ``demo`` cut at ``end_tick`` and/or starting at ``start_tick`` (see the module docstring).

    ``signature=True`` also puts the BF2Demo Analyzer welcome message into the server settings block (:mod:`bf2demo.signature`); every other
    packet stays untouched.
    """
    packets = list(demo.packets)
    if end_tick is not None:
        packets = [p for p in packets if p.tick <= end_tick]
    ticks = [p.tick for p in packets]
    if start_tick is not None:
        first = min((p.tick for p in packets if p.tick >= 0), default=0)
        squash_until = int(start_tick - lead_seconds * TICKS_PER_SECOND)
        if squash_until > first:
            collapsed = squash_until
            ticks = [collapsed if first <= t < squash_until else t for t in ticks]
    if signature:
        from .signature import sign_packet
        signed = []
        for packet in packets:
            data = sign_packet(packet.data) if packet.data else None
            signed.append(packet if data is None else DemoPacket(packet.index, packet.tick, data))
        packets = signed
    return compress(serialize(demo, packets, ticks))


def clip_file(path: str, out_path: str, start_tick: Optional[int] = None, end_tick: Optional[int] = None, lead_seconds: float = 8.0,
              signature: bool = False) -> int:
    """Write the clip of the recording at ``path`` to ``out_path``; returns the number of packets written."""
    demo = load_demo(path)
    data = make_clip(demo, start_tick, end_tick, lead_seconds, signature)
    with open(out_path, "wb") as fh:
        fh.write(data)
    return len(demo.packets)
