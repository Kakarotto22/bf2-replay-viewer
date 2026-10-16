"""Core data models shared across the parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DemoHeader:
    """The fixed header that precedes the packet stream in a demo file."""

    version: int
    server_name: str
    recorded_at: str
    map_name: str


@dataclass
class DemoPacket:
    """One framed packet: a tick/type tag plus its raw payload bytes."""

    index: int
    tick: int
    data: bytes

    @property
    def is_sync(self) -> bool:
        """Sync/lobby packet (``tick == -1``)."""
        return self.tick == -1

    @property
    def is_delimiter(self) -> bool:
        """Stream delimiter packet (``tick == -2``)."""
        return self.tick == -2

    @property
    def is_simulation(self) -> bool:
        """Simulation tick packet (``tick >= 0``)."""
        return self.tick >= 0


@dataclass
class Demo:
    """A parsed demo container."""

    header: DemoHeader
    packets: List[DemoPacket] = field(default_factory=list)
    truncated: bool = False
    trailing_bytes: int = 0
    recovered: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def map_name(self) -> str:
        return self.header.map_name

    def simulation_packets(self) -> List[DemoPacket]:
        return [p for p in self.packets if p.is_simulation]

    def first_simulation_packet(self) -> Optional[DemoPacket]:
        for packet in self.packets:
            if packet.is_simulation:
                return packet
        return None
