"""Shared helpers of the regression tests (sample loading, cached replays, ghost iteration)."""

from __future__ import annotations

import os
import unittest
from functools import lru_cache
from typing import Iterator, Tuple

from bf2demo.packet import GHOST_UPDATE, GhostRecord, PacketError, parse_packet
from bf2demo.reader import load_demo
from bf2demo.replay import Replay, build_replay

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "samples")


def sample_path(name: str) -> str:
    path = os.path.join(SAMPLES, name)
    if not os.path.isfile(path):
        raise unittest.SkipTest(f"sample {name} not present")
    return path


def demo(name: str):
    return load_demo(sample_path(name))


@lru_cache(maxsize=None)
def replay(name: str) -> Replay:
    """The replay of a sample, built once per test run (building is the slow part of most tests)."""
    return build_replay(demo(name))


def ghost_updates(rep: Replay, start_tick: int = 0) -> Iterator[Tuple[object, GhostRecord]]:
    """``(packet, ghost record)`` of every ghost update; packets the layout cannot parse (a truncated tail) are skipped."""
    for packet in rep.demo.packets:
        if not packet.data or packet.tick < start_tick:
            continue
        try:
            ghosts = parse_packet(packet.data).ghosts
        except PacketError:
            continue
        for ghost in ghosts:
            if ghost.action == GHOST_UPDATE:
                yield packet, ghost


def all_samples(max_bytes: int = 3_000_000):
    """Names of the sample demos; the large full-round ones only with ``BF2DEMO_SLOW=1``."""
    if not os.path.isdir(SAMPLES):
        return []
    names = sorted(n for n in os.listdir(SAMPLES) if n.endswith(".bf2demo"))
    if os.environ.get("BF2DEMO_SLOW"):
        return names
    return [n for n in names if os.path.getsize(os.path.join(SAMPLES, n)) <= max_bytes]
