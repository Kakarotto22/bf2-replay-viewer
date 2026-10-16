"""One-time extractor: reproduce the server's ObjectTemplate id assignment.

``CreateObjectEvent``/``CreateKitEvent``/``KilledByEvent`` carry 32-bit
``ObjectTemplate::getId()`` values. Those ids are not hashes: they are handed
out sequentially by ``ObjectTemplateManager::createTemplate`` (0x083238f0)
from the counter at ``this+0x24`` in creation order (``SoundObjectTemplate``
sets flag 0x2000 and uses the separate ``this+0x28`` counter starting at
0x1000000). Re-creating an existing name reuses the template (no new id).

Creation order on the 1.5.3153 Linux server:

1. ``GameLogicInit.con`` -> ``Common/FreeCamera/Object.con`` and one further
   engine template: ids 0..2.
2. ``GameLogic::load`` (0x080ce160) -> ``loadAllConFiles("Objects/")``
   (0x080d3e10): every ``*.con`` under ``Objects/`` (``Objects_server.zip``;
   ``Booster_server.zip`` only for the booster levels) is run in
   ``strcasecmp`` order of its path. The ``\\common\\`` -> ``\\aaa...\\``
   reordering trick in that function never fires on Linux because paths use
   ``/``.
3. The level ``Init.con`` (non-editor branch; its ``Sky.con`` pulls two
   templates from ``common_server.zip``), then
   ``GameModes/<mode>/<size>/GamePlayObjects.con``.

Known gap: the level layer is short by a small per-level constant (2..16
templates, identical for every mode/size of a level) created between the
level objects and the control points by something not yet identified. The
parser therefore aligns the level layer on the control-point block observed
in the demo instead of trusting absolute level ids.

Validated against the demos: kit, soldier, vehicle, weapon and control-point
template ids all land on their expected templates.

Usage::

    python scripts/build_templates.py [server_mod_root] [output_json]

``server_mod_root`` is a directory containing ``objects_server.zip`` and
``levels/<name>/server.zip`` (the retail ``mods/bf2`` folder works).
"""

from __future__ import annotations

import gzip
import json
import os
import posixpath
import re
import sys
import zipfile
from typing import Dict, Iterable, List, Optional, Tuple

BS = chr(92)
#: Templates created before ``Objects/`` (FreeCamera x2 + one engine template).
STARTUP_TEMPLATE_COUNT = 3
STARTUP_TEMPLATES = [("FreeCamera", "MultiPlayerFreeCamera"), ("FreeCamera", "defaultCamera"),
                     ("Unknown", "engine_template_2")]
BOOSTER_LEVELS = {"midnight_sun", "operationharvest", "operationroadrage"}

_CREATE = re.compile(r"^ObjectTemplate\.create\s+(\w+)\s+(\S+)", re.I)
_ACTIVE = re.compile(r"^ObjectTemplate\.active(?:Safe)?\s+(?:\w+\s+)?(\S+)\s*$", re.I)
_MOBILE = re.compile(r"^ObjectTemplate\.hasMobilePhysics\s+(\S+)", re.I)
_ARMOR = re.compile(r"^ObjectTemplate\.armor\.(maxHitPoints|wreckHitPoints)\s+(\S+)", re.I)
_ADD = re.compile(r"^ObjectTemplate\.addTemplate\s+(\S+)", re.I)
_NETINFO = re.compile(r"^ObjectTemplate\.setNetworkableInfo\s+(\S+)", re.I)
_HUDNAME = re.compile(r'^ObjectTemplate\.(?:vehicleHud|weaponHud)\.hudName\s+"?([^"]+?)"?\s*$', re.I)


#: the .con files spell a few template classes inconsistently (the engine compares class names case-insensitively); the asset
#: stores the dominant spelling so the parser can compare class names exactly
CLASS_SPELLING = {"bundle": "Bundle", "destroyableobject": "DestroyableObject", "decal": "Decal"}


class Archive:
    """Case-insensitive view over one or more zip files mounted at a prefix."""

    def __init__(self) -> None:
        self._files: Dict[str, Tuple[zipfile.ZipFile, str, str]] = {}

    def mount(self, path: str, prefix: str = "") -> None:
        zf = zipfile.ZipFile(path)
        for name in zf.namelist():
            mounted = posixpath.normpath(posixpath.join(prefix, name))
            self._files.setdefault(mounted.lower(), (zf, name, mounted))

    def read(self, path: str) -> Optional[str]:
        entry = self._files.get(posixpath.normpath(path).lower())
        if entry is None:
            return None
        return entry[0].read(entry[1]).decode("latin1")

    def names(self, prefix: str) -> List[str]:
        prefix = prefix.lower()
        return [entry[2] for key, entry in self._files.items() if key.startswith(prefix)]


class TemplateRegistry:
    """Mirror of ObjectTemplateManager's id counters."""

    def __init__(self) -> None:
        self.templates: List[Tuple[str, str]] = list(STARTUP_TEMPLATES)
        self._known = {name.lower() for _, name in self.templates}
        #: ``ObjectTemplate.hasMobilePhysics`` per template name (lower case)
        self.mobile: Dict[str, int] = {}
        #: ``vehicleHud.hudName`` / ``weaponHud.hudName`` (a localisation key) per template
        self.hud: Dict[str, str] = {}
        #: ``armor.maxHitPoints`` / ``armor.wreckHitPoints`` per template: they size the mask-0x10 field
        #: of SimpleObjectNetworkable (width_for(max + wreck))
        self.armor: Dict[str, Dict[str, float]] = {}
        #: ``addTemplate`` children (in file order) and ``setNetworkableInfo`` per template
        self.children: Dict[str, List[str]] = {}
        self.netinfo: Dict[str, str] = {}
        self.classes: Dict[str, str] = {}
        #: every other ``ObjectTemplate.*`` property line per template (normalised) - used for networkable analysis
        self.props: Dict[str, List[str]] = {}
        self.active: Optional[str] = None

    def create(self, cls: str, name: str) -> None:
        self.active = name.lower()
        self.classes.setdefault(name.lower(), cls)
        if cls.lower() == "sound":          # SoundObjectTemplate: flag 0x2000 counter
            return
        if name.lower() in self._known:     # existing template is reused
            return
        self._known.add(name.lower())
        self.templates.append((cls, name))

    def entry(self, cls: str, name: str) -> list:
        cls = CLASS_SPELLING.get(cls.lower(), cls)
        mobile = self.mobile.get(name.lower())
        armor = self.armor.get(name.lower())
        net = self._netseq(cls, name)
        if armor is not None or net:
            out = [cls, name, mobile, *self._armor_values(name.lower())]
            if net:
                out += list(net)
            return out
        return [cls, name] if mobile is None else [cls, name, mobile]

    #: ``ArmorTemplate`` defaults: ``armor.maxHitPoints`` and ``armor.wreckHitPoints`` are both 10 (makeScript 0x0821f840 prints a value
    #: only when it differs from the constant 10.0 at 0x0888b588). They size the health field, so an unset one still counts.
    ARMOR_DEFAULT = 10.0

    def _armor_values(self, name: str):
        armor = self.armor.get(name)
        if armor is None:
            return (None, None)
        return (armor.get("maxhitpoints", self.ARMOR_DEFAULT), armor.get("wreckhitpoints", self.ARMOR_DEFAULT))

    def _netseq(self, cls: str, name: str):
        """``(sequence letters, engine parameters, nested PCO children)`` of a PlayerControlObject ghost (see scripts/netseq.py)."""
        if cls.lower() not in ("playercontrolobject", "parachute"):      # Parachute is a PlayerControlObject root as well
            return None
        import netseq
        letters, engines = self._sequence(name.lower())
        children = []

        def walk(parent: str) -> None:
            for child in self.children.get(parent, []):
                if self.classes.get(child, "?").lower() == "playercontrolobject":
                    children.append([*self._sequence(child), self._has_camera(child)])
                walk(child)

        walk(name.lower())
        return (letters, engines, children) if children else (letters, engines)

    @staticmethod
    def _vec(p, key):
        """``ObjectTemplate.<key> a/b/c`` as three floats (missing: zeros)."""
        try:
            parts = [float(x) for x in p.get(key, "").split("/")]
        except ValueError:
            parts = []
        return (parts + [0.0, 0.0, 0.0])[:3]

    def _has_camera(self, name: str) -> bool:
        """The PCO owns a ``Camera`` template (nested PCOs excluded): ``getOwnCameras()`` is then non-empty, which selects the
        4-bit weapon block instead of the length-prefixed wrapped networkable in ``PlayerControlObjectNetworkable::setNetUpdate``."""
        for child in self.children.get(name, []):
            cls = self.classes.get(child, "?").lower()
            if cls != "playercontrolobject" and (cls == "camera" or self._has_camera(child)):
                return True
        return False

    def _sequence(self, name: str):
        """``(letters, elements)``: one info dict per letter, aligned with the letters (see ``objectnet.decode_vehicle``)."""
        import netseq
        groups = netseq.derive_groups(self, name)
        letters = "".join(g[0] for g in groups)
        elements = []
        for letter, tname, _ in groups:
            p = netseq._props(self, tname)
            if letter == "E":
                gears = p.get("setnumberofgears")
                lo, hi = self._vec(p, "setminrotation"), self._vec(p, "setmaxrotation")
                elements.append({"gears": int(float(gears)) if gears else None, "type": p.get("setenginetype"),
                                 "limits": [max(abs(lo[2]), abs(hi[2])), max(abs(lo[0]), abs(hi[0]))]})
            elif letter == "R":
                elements.append({"max_speed": [abs(v) for v in self._vec(p, "setmaxspeed")]})
            elif letter == "O":        # SimpleObject element (Rotor): its own physics flag and armor decide the optional fields
                values = self._armor_values(tname)
                total = int(values[0] or 0) + int(values[1] or 0)
                elements.append({"object": {"mobile": bool(self.mobile.get(tname)), "range_total": total}})
            else:
                elements.append({})
        return letters, elements


class ConRunner:
    """Minimal Refractor console-script interpreter (template creation only)."""

    def __init__(self, archive: Archive, registry: TemplateRegistry) -> None:
        self.archive = archive
        self.registry = registry

    def run(self, path: str, args: Iterable[str] = ()) -> bool:
        text = self.archive.read(path)
        if text is None:
            return False
        args = list(args)
        stack: List[bool] = []          # active flags of enclosing if-blocks
        rem = False
        base = posixpath.dirname(path)
        for raw in text.splitlines():
            line = raw.strip()
            low = line.lower()
            if low.startswith("beginrem"):
                rem = True
                continue
            if low.startswith("endrem"):
                rem = False
                continue
            if rem or not line or low.startswith("rem"):
                continue
            words = line.split()
            head = words[0].lower()
            if head == "if":
                stack.append(self._eval(words[1:], args))
                continue
            if head == "else":
                if stack:
                    stack[-1] = not stack[-1]
                continue
            if head == "endif":
                if stack:
                    stack.pop()
                continue
            if not all(stack):
                continue
            match = _CREATE.match(line)
            if match:
                self.registry.create(match.group(1), match.group(2))
                continue
            match = _ACTIVE.match(line)
            if match:
                self.registry.active = match.group(1).lower()
                continue
            match = _HUDNAME.match(line)
            if match and self.registry.active:
                self.registry.hud.setdefault(self.registry.active, match.group(1))
                continue
            if low.startswith("objecttemplate.") and self.registry.active and not _CREATE.match(line)                     and not _ACTIVE.match(line):
                self.registry.props.setdefault(self.registry.active, []).append(" ".join(words))
            match = _ADD.match(line)
            if match and self.registry.active:
                self.registry.children.setdefault(self.registry.active, []).append(match.group(1).lower())
                continue
            match = _NETINFO.match(line)
            if match and self.registry.active:
                self.registry.netinfo[self.registry.active] = match.group(1)
                continue
            if self.registry.active and re.match(r"^ObjectTemplate\.createComponent\s+Armor\b", line, re.I):
                self.registry.armor.setdefault(self.registry.active, {})      # Armor component: unset values keep the defaults
                continue
            match = _ARMOR.match(line)
            if match and self.registry.active:
                try:
                    self.registry.armor.setdefault(self.registry.active, {}).setdefault(
                        match.group(1).lower(), float(match.group(2)))
                except ValueError:
                    pass
                continue
            match = _MOBILE.match(line)
            if match and self.registry.active:
                try:
                    self.registry.mobile[self.registry.active] = int(float(match.group(1)))
                except ValueError:
                    pass
                continue
            if head in ("run", "include") and len(words) > 1:
                target = words[1].replace(BS, "/")
                if target.startswith("/"):
                    target = target.lstrip("/")
                else:
                    target = posixpath.join(base, target)
                self.run(target, [self._subst(w, args) for w in words[2:]])
        return True

    @staticmethod
    def _subst(word: str, args: List[str]) -> str:
        m = re.fullmatch(r"v_arg(\d+)", word, re.I)
        if m:
            i = int(m.group(1)) - 1
            return args[i] if i < len(args) else ""
        return word

    def _eval(self, cond: List[str], args: List[str]) -> bool:
        if len(cond) >= 3 and cond[1] == "==":
            return self._subst(cond[0], args).lower() == self._subst(cond[2], args).strip('"').lower()
        if len(cond) >= 3 and cond[1] == "!=":
            return self._subst(cond[0], args).lower() != self._subst(cond[2], args).strip('"').lower()
        return False


def objects_order(archive: Archive) -> List[str]:
    cons = [n for n in archive.names("objects/") if n.lower().endswith(".con")]
    return sorted(cons, key=lambda p: p.lower())


def _mount_mod(archive: Archive, mod_root: str, overlay_root: Optional[str], name: str, prefix: str) -> None:
    """Mount ``name`` of ``overlay_root`` (a mod such as ``xpack`` that mounts the base mod's archives behind its own) and ``mod_root``."""
    if overlay_root:
        archive.mount(_find(overlay_root, name), prefix)
    archive.mount(_find(mod_root, name), prefix)


def build_global(mod_root: str, booster: bool = False, overlay_root: Optional[str] = None) -> TemplateRegistry:
    archive = Archive()
    _mount_mod(archive, mod_root, overlay_root, "objects_server.zip", "objects")
    if booster:
        archive.mount(_find(mod_root, "booster_server.zip"), "objects")
    registry = TemplateRegistry()
    runner = ConRunner(archive, registry)
    for path in objects_order(archive):
        runner.run(path)
    return registry


def build_level(mod_root: str, level: str, global_templates, overlay_root: Optional[str] = None) -> Dict[str, object]:
    """Level templates (after the global block) for every mode/size layer.

    ``_init_count`` is the number of templates created by the level
    ``Init.con`` (shared by all layers) before ``GamePlayObjects.con``.
    """
    level_zip = _find(os.path.join(overlay_root or mod_root, "levels", level), "server.zip")
    out: Dict[str, List[Tuple[str, str]]] = {}
    probe = zipfile.ZipFile(level_zip)
    layers = sorted({tuple(n.split("/")[1:3]) for n in probe.namelist()
                     if n.lower().startswith("gamemodes/") and n.lower().endswith("gameplayobjects.con")})
    for mode, size in layers:
        archive = Archive()
        _mount_mod(archive, mod_root, overlay_root, "objects_server.zip", "objects")
        _mount_mod(archive, mod_root, overlay_root, "common_server.zip", "common")  # Sky.con -> Common/Sky/*
        archive.mount(level_zip, "")
        registry = TemplateRegistry()
        registry.templates = list(global_templates.templates)
        registry._known = {name.lower() for _, name in global_templates.templates}
        registry.mobile = dict(global_templates.mobile)
        registry.armor = {k: dict(v) for k, v in global_templates.armor.items()}
        runner = ConRunner(archive, registry)
        runner.run("init.con", ["host", ""])
        base = len(global_templates.templates)
        out["_init_count"] = len(registry.templates) - base
        runner.run(f"gamemodes/{mode}/{size}/gameplayobjects.con", ["host"])
        out[f"{mode.lower()}/{size}"] = [registry.entry(*t) for t in registry.templates[base:]]
    return out


def _find(directory: str, name: str) -> str:
    for entry in os.listdir(directory):
        if entry.lower() == name.lower():
            return os.path.join(directory, entry)
    raise FileNotFoundError(os.path.join(directory, name))


def load_utxt(mod_root: str) -> Dict[str, str]:
    """English localisation: UTF-16 lines ``KEY   <ESC><ESC>text<ESC><ESC>``; colour codes removed."""
    loc_dir = os.path.join(mod_root, "Localization", "English")
    texts: Dict[str, str] = {}
    if not os.path.isdir(loc_dir):
        return texts
    esc = chr(27)
    color = re.compile(chr(0xA7) + r"C\d{4}")
    line_re = re.compile(r"^(\S+?)\s*" + esc + esc + "(.*?)" + esc + esc + r"\s*$")
    for name in sorted(os.listdir(loc_dir)):
        if not name.lower().endswith(".utxt"):
            continue
        text = open(os.path.join(loc_dir, name), "rb").read().decode("utf-16", errors="replace")
        for line in text.splitlines():
            m = line_re.match(line)
            if m:
                texts[m.group(1)] = color.sub("", m.group(2))
    return texts


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    mod_root = argv[0] if argv else r"C:\Program Files (x86)\EA Games\Battlefield 2\mods\bf2"
    xpack_root = argv[2] if len(argv) > 2 else None        # optional Special Forces mod folder (mods/xpack)
    out_path = argv[1] if len(argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bf2demo", "assets", "templates.json.gz")
    global_templates = build_global(mod_root)
    booster_templates = build_global(mod_root, booster=True)
    levels = {}
    levels_dir = os.path.join(mod_root, "levels")
    for level in sorted(os.listdir(levels_dir)):
        if not os.path.isdir(os.path.join(levels_dir, level)):
            continue
        base = booster_templates if level.lower() in BOOSTER_LEVELS else global_templates
        try:
            layers = build_level(mod_root, level, base)
        except FileNotFoundError:
            continue
        levels[level.lower()] = layers
    xpack = None
    if xpack_root:
        xpack_global = build_global(mod_root, overlay_root=xpack_root)
        xpack_levels = {}
        for level in sorted(os.listdir(os.path.join(xpack_root, "levels"))):
            try:
                xpack_levels[level.lower()] = build_level(mod_root, level, xpack_global, overlay_root=xpack_root)
            except FileNotFoundError:
                continue
        xpack = {"global": [xpack_global.entry(*t) for t in xpack_global.templates], "levels": xpack_levels}
    doc = {
        "source": "objects_server.zip (BF2 1.5.3153) via scripts/build_templates.py",
        "global": [global_templates.entry(*t) for t in global_templates.templates],
        # the booster pack archive is merged into the sorted .con order, so its templates are interleaved with the base ones
        "booster_global": [booster_templates.entry(*t) for t in booster_templates.templates],
        "booster_levels": sorted(BOOSTER_LEVELS),
        "levels": levels,
    }
    if xpack is not None:
        doc["xpack"] = xpack
    opener = gzip.open if out_path.endswith(".gz") else open
    with opener(out_path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    names = load_utxt(mod_root)
    hud = {}
    for template, key in sorted(global_templates.hud.items()):
        if key in names:
            hud[template] = names[key]
    hud_path = os.path.join(os.path.dirname(out_path), "hud_names.json")
    with open(hud_path, "w", encoding="utf-8") as fh:
        json.dump({"doc": "template name (lower case) -> in-game kill-message text, from "
                          "vehicleHud/weaponHud hudName keys and the English localisation",
                   "names": hud}, fh, indent=0, ensure_ascii=False)
    print(f"hud names: {len(hud)} of {len(global_templates.hud)} keys resolved -> {hud_path}")
    print(f"global={len(global_templates.templates)} booster={len(booster_templates.templates)} "
          f"levels={len(levels)} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
