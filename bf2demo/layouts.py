"""Bundled retail ``GamePlayObjects.con`` layouts and a lossless block parser.

A layout is the full text of a level's ``GamePlayObjects.con`` (see
``scripts/build_layouts.py``). :func:`parse_layout` splits it into *static*
text and *blocks* without losing a single character, so that the exporter can
re-emit the file replacing only the values a demo actually contains.

A block starts at ``rem [<Class>Template: name]`` (a template) or
``rem [<Class>: name]`` (an instance, possibly indented) and ends at the next
blank line (which belongs to the block).
"""

from __future__ import annotations

import gzip
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

_PATH = os.path.join(os.path.dirname(__file__), "assets", "layouts.json.gz")

_BLOCK = re.compile(r"^(\s*)rem \[(ObjectSpawner|SpawnPoint|ControlPoint)(Template)?: (.+?)\]\s*$")


@dataclass
class Item:
    """Either static text (``cls`` is None) or one block."""

    lines: List[str]
    cls: Optional[str] = None          # "objectspawner" | "spawnpoint" | "controlpoint"
    is_template: bool = False
    name: str = ""

    @property
    def is_block(self) -> bool:
        return self.cls is not None

    # -- instance helpers -------------------------------------------------- #
    def prop(self, key: str) -> Optional[str]:
        """Value of ``Object.<key>`` / ``ObjectTemplate.<key>`` (first occurrence)."""
        pat = re.compile(rf"^\s*Object(?:Template)?\.{key}\s+(.*?)\s*$", re.I)
        for line in self.lines:
            m = pat.match(line)
            if m:
                return m.group(1)
        return None

    def vec(self, key: str) -> Optional[Tuple[float, ...]]:
        value = self.prop(key)
        return tuple(float(v) for v in value.split("/")) if value else None


@lru_cache(maxsize=1)
def _load() -> dict:
    """The bundled retail layouts; a public checkout leaves the file out (it is the game's own level text): exports then use ``--layout FILE`` or a generic layout."""
    if not os.path.isfile(_PATH):
        return {}
    with gzip.open(_PATH, "rt", encoding="latin1") as fh:
        return json.load(fh)["layouts"]


def layout_text(level: str, mode: Optional[str], size: Optional[int]) -> Optional[str]:
    """Retail layout text (LF line ends) for a level/mode/size, or None."""
    if not (level and mode and size):
        return None
    return _load().get(level.strip().lower(), {}).get(f"{mode.lower()}/{size}")


def parse_layout(text: str) -> List[Item]:
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    items: List[Item] = []
    static: List[str] = []
    i = 0
    while i < len(lines):
        m = _BLOCK.match(lines[i])
        if not m:
            static.append(lines[i])
            i += 1
            continue
        if static:
            items.append(Item(static))
            static = []
        j = i
        while j < len(lines) and lines[j].strip() != "":
            j += 1
        end = j + 1 if j < len(lines) else j         # the blank line belongs to the block
        items.append(Item(lines[i:end], m.group(2).lower(), bool(m.group(3)), m.group(4)))
        i = end
    if static:
        items.append(Item(static))
    return items


def render(items: List[Item]) -> str:
    """Inverse of :func:`parse_layout` (LF line ends)."""
    return "\n".join(line for it in items for line in it.lines) + "\n"
