"""Derive the networkable sequence of a world object's ghost from its template tree.

Mirrors ``NetworkManager::analyseObject`` (0x0846ada0) / ``_analyseObject`` (0x0846aa50) / ``compareProperties``
(0x0846ab10):

* depth-first, pre-order walk over the object's children (``addTemplate`` order); children that are
  ``PlayerControlObject`` are skipped with their subtrees (they have their own ghost);
* only templates with ``setNetworkableInfo`` take part;
* objects whose templates are equal, or are rotational bundles with equal min/max rotation, max speed,
  acceleration, input mapping and the setAutomaticReset flag (+0x1e8, from RotationalBundleTemplate::makeScript), share ONE group (one update is read once and applied to all of them);
  ``SpringInfo`` templates are unique (``setIsUnique``): every spring is its own group;
* the ghost body is the concatenation of the groups in order of first appearance.

Letters: R rotational bundle / camera / wing, E engine, S spring, D destroyable object, O simple object (Rotor: verified
on ahe_ah1z, its ghost carries one SimpleObjectNetworkable per rotor template).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

LETTER = {"rotationalbundle": "R", "camera": "R", "wing": "R", "floatingbundle": "R", "rotor": "O", "engine": "E", "spring": "S",
          "destroyableobject": "D", "simpleobject": "O"}
#: classes that derive from RotationalBundleTemplate (compareProperties compares their rotation properties)
RB_LIKE = {"rotationalbundle", "camera", "wing", "engine", "floatingbundle"}
UNIQUE_INFOS = {"springinfo"}
RB_KEYS = ("setminrotation", "setmaxrotation", "setmaxspeed", "setacceleration",
           "setinputtoyaw", "setinputtopitch", "setinputtoroll")


def _props(registry, name: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in registry.props.get(name, []):
        parts = line.split(None, 1)
        key = parts[0].split(".", 1)[1].lower()
        out[key] = parts[1] if len(parts) > 1 else ""
    return out


def _signature(registry, name: str, flag_key: Optional[str]):
    p = _props(registry, name)
    cls = registry.classes.get(name, "?").lower()
    sig = ("rb" if cls in ("rotationalbundle", "camera") else cls,) + tuple(p.get(k, "") for k in RB_KEYS)
    if flag_key:
        sig += (p.get(flag_key, ""),)
    return sig


def derive(registry, root: str, flag_key: Optional[str] = "setautomaticreset") -> str:
    """Sequence letters for the ghost of the object created from template ``root`` (lower case name)."""
    return "".join(g[0] for g in derive_groups(registry, root, flag_key))


def derive_groups(registry, root: str, flag_key: Optional[str] = "setautomaticreset"):
    """``[(letter, template name, signature)]`` per group, in ghost order."""
    groups: List[Tuple[str, str, object]] = []        # (letter, template name, signature or unique marker)

    def visit(name: str, depth: int) -> None:
        for child in registry.children.get(name, []):
            cls = registry.classes.get(child, "?").lower()
            if cls == "playercontrolobject":
                continue
            info = registry.netinfo.get(child)
            if info:
                letter = LETTER.get(cls)
                if letter is None:          # classes without a decoded networkable contribute nothing (verified: car_horn,
                    visit(child, depth + 1)  # decoy launcher GenericFireArm BasicInfo leave no bits in the body)
                    continue
                if info.lower() in UNIQUE_INFOS:
                    groups.append((letter, child, ("unique", len(groups))))
                else:
                    sig = _signature(registry, child, flag_key) if cls in RB_LIKE else ("template", child)
                    if not any(g[0] == letter and (g[2] == sig or g[1] == child) for g in groups):
                        groups.append((letter, child, sig))
            visit(child, depth + 1)

    visit(root.lower(), 0)
    return groups
