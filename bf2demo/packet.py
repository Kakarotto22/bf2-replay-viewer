"""Decomposition of one recorded network packet.

The demo recorder stores exactly what ``ClientConnection::transmitMsgs``
(0x08084a10) writes for the demo connection: the stream managers are asked to
``transmit`` in registration order into one BitStream, and
``DemoRecorder::writeFakePacketData`` (0x081518a0) stores the bytes. A client
replays them through ``ClientConnection::processReceivedPacket``
(0x08084900), which reads, in order:

1. ``PlayerActionManager::processReceivedPacket`` (0x0809da20)
   ``present(1)`` [``count(4) seq(9)`` ...] — never set server->client.
2. ``GameEventManager::processReceivedPacket`` (0x0808f730)
   ``present(1)`` [``count(8) seq(5) flag(1)`` then ``count`` events].
3. ``GhostManager::processReceivedPacket`` (0x08098780)
   ``present(1)`` [``time(32) count(8) hasControl(1)`` [control state]
   then ``count`` ghost records].

Ghost records (``GhostManager::readData`` @ 0x08095df0) are
``action(2) ghost_id(16)``; action 1 (update) adds ``flag(1)`` and a
``length`` field whose width is ``GhostManager+0x2178`` followed by
``length`` bits of networkable state; action 3 removes the ghost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .bitstream import BitStream
from .events import EID_BITS, EventReadError, GameEvent, read_event

GHOST_NONE, GHOST_UPDATE, GHOST_ERROR, GHOST_REMOVE = 0, 1, 2, 3

#: ``GhostManager+0x2178`` width for the demo connection's ghost manager.
GHOST_LENGTH_BITS = 13


class PacketError(Exception):
    """Raised when a packet does not follow the transmitted layout."""


@dataclass(slots=True)
class GhostRecord:
    action: int
    ghost_id: int
    is_new: bool = False
    bit_start: int = 0          # first bit of the networkable state
    bit_length: int = 0


@dataclass
class Packet:
    events: List[GameEvent] = field(default_factory=list)
    event_seq: Optional[int] = None
    event_flag: Optional[bool] = None
    ghost_time: Optional[int] = None
    ghosts: List[GhostRecord] = field(default_factory=list)
    has_control_state: bool = False
    end_bit: int = 0
    total_bits: int = 0


def parse_packet(data: bytes, eid_bits: int = EID_BITS,
                 ghost_length_bits: int = GHOST_LENGTH_BITS) -> Packet:
    bs = BitStream(data)
    pkt = Packet(total_bits=len(data) * 8)

    if bs.read_bits(1):
        raise PacketError("PlayerActionManager block present (not expected server->client)")

    if bs.read_bits(1):
        count = bs.read_bits(8)
        pkt.event_seq = bs.read_bits(5)
        pkt.event_flag = bs.read_bits(1) == 1
        for _ in range(count):
            try:
                pkt.events.append(read_event(bs, eid_bits))
            except EventReadError as exc:
                raise PacketError(str(exc)) from exc

    if bs.read_bits(1):
        pkt.ghost_time = bs.read_bits(32)
        count = bs.read_bits(8)
        if bs.read_bits(1):
            pkt.has_control_state = True
            raise PacketError("control-object state present (readControlObjectState)")
        ghosts = pkt.ghosts
        head_bits = 2 + 16 + 1 + ghost_length_bits
        for _ in range(count):
            # one read for the whole header of an update record (action, id, is_new, length); other records only use the first 18 bits
            start = bs._pos
            head = bs.read_bits(head_bits)
            action = head & 3
            ghost_id = (head >> 2) & 0xFFFF
            if action == GHOST_UPDATE:
                rec = GhostRecord(action, ghost_id, (head >> 18) & 1 == 1, bs._pos, head >> 19)
                bs._pos += rec.bit_length  # skip; decoded per networkable class
            else:
                bs._pos = start + 18
                if action == GHOST_ERROR:
                    raise PacketError(f"ghost error record for id {ghost_id}")
                rec = GhostRecord(action, ghost_id)
            ghosts.append(rec)

    if bs.bit_pos > pkt.total_bits:
        raise PacketError(f"packet overran by {bs.bit_pos - pkt.total_bits} bits")
    pkt.end_bit = bs.bit_pos
    return pkt
