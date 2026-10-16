"""Rest-height offsets of mobile vehicles (settled Y minus spawner Y).

A recording that starts after a vehicle spawned only sees its settled position (the join snapshot
sends live positions, see ``ServerConnection::clientSendDatabase`` 0x0808a020). For ground
vehicles the offset is the same at every spawner of a template, so the spawner Y can be
estimated. The table is learned by ``scripts/build_settle_table.py`` from recordings made at map
load on unmodified retail maps; only templates with at least ``MIN_SAMPLES`` observations of which 90% lie within
``MAX_SPREAD`` of the median are used (measured on a customised Taraba Quarry whose real spawner coordinates are known:
median error of all snapshot-only vehicles 0.13 m, 1 to 2 cm for the usable templates). Aircraft are not usable (they
spawn both on the ground and on the carrier deck).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional

_PATH = os.path.join(os.path.dirname(__file__), "assets", "settle_offsets.json")
MIN_SAMPLES = 3
MAX_SPREAD = 0.10                       # metres


@lru_cache(maxsize=1)
def _table() -> dict:
    with open(_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)["templates"]


def settle_offset(template_name: str) -> Optional[float]:
    entry = _table().get(template_name.lower())
    if entry and entry["n"] >= MIN_SAMPLES and entry.get("spread", 1.0) <= MAX_SPREAD:
        return float(entry["dy"])
    return None


def settle_spread(template_name: str) -> Optional[float]:
    """90th percentile of the deviation from :func:`settle_offset` over the learned spawners (metres)."""
    entry = _table().get(template_name.lower())
    return float(entry["spread"]) if entry and settle_offset(template_name) is not None else None
