"""``PostRemoteEvent`` payloads: server -> client EventManager events.

Wire layout (``PostRemoteEvent::deSerialize`` 0x08077a70): category(4) id(32) delay(float32) len(8) data.
``(category, id)`` is the EventManager event the client raises; names come from the registerEvent calls
in BF2.exe (``assets/event_names.json``). Events sent to a single player (``sendGameEvent(player, ..)``) never
reach a recording: assists, replenish and team-damage messages are unicast.
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, Optional

_PATH = os.path.join(os.path.dirname(__file__), "assets", "event_names.json")

#: Hud events (category 2) that forward a ``SpottedEvent`` (24-byte struct, id = ``SpottedEvent+0x20``).
SPOT_IDS = (0x2b, 0x2e, 0x2f, 0x30, 0x31, 0x32, 0x33)


@lru_cache(maxsize=1)
def _names() -> Dict[str, Dict[str, str]]:
    with open(_PATH, encoding="utf-8") as fh:
        return json.load(fh)["events"]


def event_name(category: int, event_id: int) -> str:
    return _names().get(str(category), {}).get(str(event_id)) or f"event_{category}_{event_id}"


@dataclass
class RemoteEvent:
    category: int
    event_id: int
    name: str
    fields: Dict[str, object] = field(default_factory=dict)


def decode_post_remote(ev) -> RemoteEvent:
    """Name and payload fields of a decoded ``PostRemote`` game event."""
    category, event_id, data = ev["kind"], ev["value"], ev["data"]
    out = RemoteEvent(category, event_id, event_name(category, event_id))
    f = out.fields
    if category == 2 and len(data) == 24 and event_id in SPOT_IDS:
        a, b, flags, x, z, tag, ident = struct.unpack("<hhIffII", data)
        f.update(object_a=a, object_b=b, byte_10=flags & 0xFF, x=x, z=z, spot_tag=tag, spot_id=ident)
    elif category == 6 and event_id in (9, 10) and len(data) >= 4:
        f["player_id"] = struct.unpack_from("<I", data)[0]
        if event_id == 10 and len(data) >= 8:
            f["no_killer"] = struct.unpack_from("<I", data, 4)[0] == 1
    elif category == 0 and event_id in (19, 20) and len(data) == 8:
        f["object_id"], f["team"] = struct.unpack("<II", data)
    elif category == 0 and event_id in (21, 22, 23) and len(data) == 4:
        f["object_id"] = struct.unpack("<I", data)[0]
    elif category == 0 and event_id == 1 and len(data) == 4:
        f["game_status"] = struct.unpack("<I", data)[0]
    elif category == 2 and event_id == 0x21 and len(data) == 8:
        f["player_id"], f["value"] = struct.unpack("<If", data)
    elif category == 2 and event_id in (0x22, 0x25, 0x23) and len(data) == 4:
        f["player_id"] = struct.unpack("<I", data)[0]
    elif data:
        f["raw"] = data.hex()
    return out
