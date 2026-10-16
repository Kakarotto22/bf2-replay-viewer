"""Demo time: ticks to seconds.

The simulation runs at 30 ticks per second. Evidence: a vote that is not decided early runs out exactly 90 seconds after its
start event (``Vote`` events at ticks 1345 and 4046 of ``auto_2026_08_01_00_36_33``: 2701 ticks, ``time_remaining`` 90.0 -> 0.0),
and a 40 minute server round is scheduled 72000 ticks after it begins (``BeginRound.next_state_change_tick`` 72151 for a round that
began at tick 151).
"""

from __future__ import annotations

from typing import Optional

TICKS_PER_SECOND = 30


def format_span(ticks: int) -> str:
    """``mm:ss`` (or ``h:mm:ss``) of a number of ticks."""
    seconds = max(0, round(ticks / TICKS_PER_SECOND))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def format_tick(tick: int, origin: Optional[int]) -> str:
    """Time of ``tick`` since ``origin`` (the first simulation tick of the demo); lobby ticks (< 0) are shown as ``--:--``."""
    if tick < 0 or origin is None:
        return "--:--"
    return format_span(tick - origin)
