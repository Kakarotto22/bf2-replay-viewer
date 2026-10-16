"""Development tool: which weapon a soldier holds for a given ``weapon_item_index``.

A soldier's ghost carries ``weapon_item_index`` (``SoldierNetworkable``, ``getItemIndex`` of the weapon in hand). Every weapon template has
``ObjectTemplate.itemIndex`` (its slot, in the ``.tweak`` files), and a kit's weapons are its ``addTemplate`` list plus the unlock containers
(``ItemContainer Unlock...``: ``addTemplate`` = the unlocked weapon, ``replaceItem`` = the default one it replaces). The table
``bf2demo/assets/weapon_slots.json`` is ``kit template (lower case) -> {item index: [weapon templates, default first]}``.

The parser never reads game files; it uses this bundled table.

Usage: python scripts/build_weapon_slots.py [mods root, default C:\\Program Files (x86)\\EA Games\\Battlefield 2\\mods]
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from typing import Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATE = re.compile(r"^\s*ObjectTemplate\.(?:create|activeSafe)\s+(\w+)\s+(\S+)", re.I)
ADD = re.compile(r"^\s*ObjectTemplate\.addTemplate\s+(\S+)", re.I)
REPLACE = re.compile(r"^\s*ObjectTemplate\.replaceItem\s+(\S+)", re.I)
INDEX = re.compile(r"^\s*ObjectTemplate\.itemIndex\s+(\d+)", re.I)


def read_archives(mods: str, mod: str) -> List[str]:
    texts: List[str] = []
    folder = os.path.join(mods, mod)
    for name in sorted(os.listdir(folder)):
        if name.lower().startswith(("objects_server", "booster_server")) and name.lower().endswith(".zip"):
            with zipfile.ZipFile(os.path.join(folder, name)) as z:
                for member in z.namelist():
                    if member.lower().endswith((".con", ".tweak")) and member.lower().startswith(("kits/", "weapons/")):
                        texts.append(z.read(member).decode("latin1"))
    return texts


def parse(texts: List[str]):
    item_index: Dict[str, int] = {}
    children: Dict[str, List[str]] = {}
    replaces: Dict[str, List[str]] = {}
    classes: Dict[str, str] = {}
    for text in texts:
        current = None
        for line in text.splitlines():
            m = CREATE.match(line)
            if m:
                current = m.group(2).lower()
                classes.setdefault(current, m.group(1))
                continue
            if current is None:
                continue
            m = ADD.match(line)
            if m:
                children.setdefault(current, []).append(m.group(1).lower())
                continue
            m = REPLACE.match(line)
            if m:
                replaces.setdefault(current, []).append(m.group(1).lower())
                continue
            m = INDEX.match(line)
            if m:
                item_index[current] = int(m.group(1))
    return item_index, children, replaces, classes


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    mods = argv[0] if argv else r"C:\Program Files (x86)\EA Games\Battlefield 2\mods"
    item_index, children, replaces, classes = {}, {}, {}, {}
    for mod in ("bf2", "xpack"):
        if not os.path.isdir(os.path.join(mods, mod)):
            continue
        a, b, c, d = parse(read_archives(mods, mod))
        item_index.update(a)
        for k, v in b.items():
            children.setdefault(k, v)
        for k, v in c.items():
            replaces.setdefault(k, v)
        classes.update(d)
    kits: Dict[str, Dict[str, List[str]]] = {}
    for name, cls in classes.items():
        if cls.lower() != "kit":
            continue
        slots: Dict[str, List[str]] = {}
        for child in children.get(name, []):
            if classes.get(child, "").lower() == "itemcontainer":             # an unlock: its weapons are alternatives of the replaced item
                for weapon in children.get(child, []):
                    if weapon in item_index:
                        slots.setdefault(str(item_index[weapon]), []).append(weapon)
            elif child in item_index:
                slots.setdefault(str(item_index[child]), []).insert(0, child)
        kits[name] = slots
    out = {"doc": "kit template (lower case) -> weapon item index (SoldierNetworkable weapon_item_index) -> weapon templates, default first, unlocks after",
           "kits": kits}
    path = os.path.join(ROOT, "bf2demo", "assets", "weapon_slots.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=0, sort_keys=True)
    print(f"{len(kits)} kits, {len(item_index)} weapons with an item index -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
