"""How many bits of a demo are understood?

Every packet is split into the pieces the protocol defines (manager flags and counters, game events, ghost record headers, ghost
bodies, final padding). A ghost body counts as understood only when the decoder for its owner consumes *exactly* the recorded
number of bits, so the figure is a hard statement about the decoders, not an estimate.

``decode_ghost_body`` is the single dispatch from a ghost id to the matching decoder; the report, the tests and
``scripts/bit_coverage.py`` use it.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .bitstream import BitStream
from .networkables import decode_control_point, decode_player, decode_score_manager, decode_spawn_group
from .objectnet import (SimpleObjectContext, UnsupportedLayout, decode_child_pco, decode_destroyable,
                        decode_generic_projectile, decode_overhead_camera, decode_simple_object, decode_soldier,
                        decode_triggerable_target, decode_vehicle)
from .packet import GHOST_UPDATE, GhostRecord, PacketError, parse_packet
from .replay import Replay

#: classes whose ghost body is exactly one SimpleObjectNetworkable
_SIMPLE_CLASSES = ("SimpleObject", "Triggerable", "SupplyObject", "UAVVehicle")
#: bytes of a ghost record header: action(2) + id(16), and for updates isNew(1) + length(13)
_RECORD_HEADER_BITS = {True: 18 + 14, False: 18}


class GhostOwners:
    """Which entity a ghost id belongs to (control point, player, spawn group, score manager or world object)."""

    def __init__(self, replay: Replay) -> None:
        self.replay = replay
        self.control_points = set(replay.control_points)
        self.players = {p.ghost_id for p in replay.player_history}
        self.spawn_groups = {e["object_id"] for _, e in replay.events if e.name == "CreateSpawnGroup"}


def decode_ghost_body(owners: GhostOwners, ghost: GhostRecord, data: bytes, tick: int) -> Optional[int]:
    """Bits consumed by the decoder of the ghost's owner, or ``None`` when no decoder applies or it fails."""
    replay = owners.replay
    try:
        if ghost.ghost_id in owners.control_points:
            return decode_control_point(data, ghost.bit_start).bits
        if ghost.ghost_id in owners.players:
            return decode_player(data, ghost.bit_start).bits
        if ghost.ghost_id in owners.spawn_groups:
            return decode_spawn_group(data, ghost.bit_start).bits
        if ghost.ghost_id == replay.score_manager_id:
            return decode_score_manager(data, ghost.bit_start).bits
        bs = BitStream(data, ghost.bit_start)
        obj = replay.object_at(ghost.ghost_id, tick)
        if obj is None:
            owner = replay.nested_owner(ghost.ghost_id, tick)
            return decode_child_pco(bs, owner[0].template, owner[1]) if owner else None
        template = obj.template
        if template is None:
            return None
        cls = template.cls
        if cls == "Soldier":
            return decode_soldier(bs).bits
        if cls in _SIMPLE_CLASSES:
            return decode_simple_object(bs, SimpleObjectContext(bool(template.mobile), template.range_bits)).bits
        if cls == "TriggerableTarget":
            return decode_triggerable_target(bs).bits
        if cls == "DestroyableObject":
            return decode_destroyable(bs, template.range_bits).bits
        if cls == "OverheadCamera":
            return decode_overhead_camera(bs).bits
        if cls == "GenericProjectile":
            return decode_generic_projectile(bs, template.range_bits).bits
        if cls in ("PlayerControlObject", "Parachute") and template.netseq is not None:
            return decode_vehicle(bs, template)
    except UnsupportedLayout:
        return None
    return None


@dataclass
class CoverageReport:
    total_bits: int = 0
    event_bits: int = 0
    record_header_bits: int = 0
    framing_bits: int = 0               # manager flags, event counter/sequence, ghost time/count and the final padding
    decoded_body_bits: int = 0
    undecoded_bits: Dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    undecoded_updates: Dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    #: ``(ghost id, tick, bits, owner description)`` of every body no decoder explained
    undecoded_records: List[Tuple[int, int, int, str]] = field(default_factory=list)

    @property
    def understood_bits(self) -> int:
        return self.event_bits + self.record_header_bits + self.framing_bits + self.decoded_body_bits

    @property
    def understood_ratio(self) -> float:
        return self.understood_bits / self.total_bits if self.total_bits else 1.0

    @property
    def complete(self) -> bool:
        """Every body was explained exactly (packets that could not be parsed at all are not counted in the total)."""
        return not self.undecoded_records


def _describe_owner(replay: Replay, ghost_id: int, tick: int) -> str:
    obj = replay.object_at(ghost_id, tick)
    if obj is not None and obj.template is not None:
        return f"{obj.template.cls} ({obj.template.name})"
    owner = replay.nested_owner(ghost_id, tick)
    if owner is not None:
        return f"nested PlayerControlObject {owner[1]} of {owner[0].template.name}"
    return "unknown id"


def analyse(replay: Replay) -> CoverageReport:
    owners = GhostOwners(replay)
    report = CoverageReport()
    for packet in replay.demo.packets:
        if not packet.data:
            continue
        try:
            parsed = parse_packet(packet.data)
        except PacketError:
            continue
        report.total_bits += parsed.total_bits
        events = sum(e.bit_end - e.bit_start for e in parsed.events)
        headers = sum(_RECORD_HEADER_BITS[g.action == GHOST_UPDATE] for g in parsed.ghosts)
        bodies = sum(g.bit_length for g in parsed.ghosts if g.action == GHOST_UPDATE)
        report.event_bits += events
        report.record_header_bits += headers
        report.framing_bits += parsed.total_bits - events - headers - bodies
        for ghost in parsed.ghosts:
            if ghost.action != GHOST_UPDATE:
                continue
            if decode_ghost_body(owners, ghost, packet.data, packet.tick) == ghost.bit_length:
                report.decoded_body_bits += ghost.bit_length
                continue
            kind = _describe_owner(replay, ghost.ghost_id, packet.tick)
            report.undecoded_bits[kind] += ghost.bit_length
            report.undecoded_updates[kind] += 1
            report.undecoded_records.append((ghost.ghost_id, packet.tick, ghost.bit_length, kind))
    return report


def format_report(name: str, replay: Replay, report: CoverageReport) -> str:
    total = report.total_bits or 1
    lines = [f"{name}: {report.total_bits / 8 / 1024:.0f} KiB in {len(replay.demo.packets)} packets",
             f"  game events                {report.event_bits / total:6.1%}",
             f"  ghost record headers       {report.record_header_bits / total:6.1%}",
             f"  packet framing + padding   {report.framing_bits / total:6.1%}",
             f"  ghost bodies decoded       {report.decoded_body_bits / total:6.1%}"]
    for kind, bits in sorted(report.undecoded_bits.items(), key=lambda kv: -kv[1])[:12]:
        lines.append(f"  NOT understood: {kind:34} {bits / total:6.1%}  ({report.undecoded_updates[kind]} updates)")
    lines.append(f"  => understood: {report.understood_ratio:.1%} of all bits")
    return "\n".join(lines)
