"""Minimal parser for Refractor ``.con`` object definition files.

Only what is needed to read ``GamePlayObjects.con``: template definitions
(``ObjectTemplate.create <Class> <Name>`` and their properties) and object
instances (``Object.create`` with position, rotation and properties).
"""

from __future__ import annotations

import re
from typing import Dict, List


def parse(text: str) -> Dict[str, List[dict]]:
    templates: Dict[str, dict] = {}
    cur = None
    inst = None
    out: Dict[str, List[dict]] = {"objectspawner": [], "spawnpoint": [], "controlpoint": []}
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"ObjectTemplate\.create\s+(\w+)\s+(\S+)", line, re.I)
        if m:
            cur = {"class": m.group(1).lower(), "name": m.group(2), "slots": {}, "slots_raw": {}, "props": {}}
            templates[m.group(2).lower()] = cur
            continue
        m = re.match(r"ObjectTemplate\.setObjectTemplate\s+(\d+)\s+(\S+)", line, re.I)
        if m and cur:
            cur["slots"][int(m.group(1))] = m.group(2).lower()
            cur["slots_raw"][int(m.group(1))] = m.group(2)
            continue
        m = re.match(r"ObjectTemplate\.(\w+)\s+(.*)", line, re.I)
        if m and cur:
            cur["props"][m.group(1).lower()] = m.group(2).strip()
            continue
        m = re.match(r"Object\.create\s+(\S+)", line, re.I)
        if m:
            tpl = templates.get(m.group(1).lower())
            inst = {"name": m.group(1), "tpl": tpl, "pos": None, "rot": (0.0, 0.0, 0.0), "props": {}}
            if tpl and tpl["class"] in out:
                out[tpl["class"]].append(inst)
            continue
        m = re.match(r"Object\.(\w+)\s+(.*)", line, re.I)
        if m and inst:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "absoluteposition":
                inst["pos"] = tuple(float(v) for v in val.split("/"))
            elif key == "rotation":
                inst["rot"] = tuple(float(v) for v in val.split("/"))
            else:
                inst["props"][key] = val
    return out
