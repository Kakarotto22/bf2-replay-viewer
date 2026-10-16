"""In-game HUD artwork, fonts and names, taken from the player's own Battlefield 2 install into a small private store.

Nothing from the game is stored in the repository. The HUD textures live in ``Menu_client.zip`` (``HUD/Texture/Ingame/...``), the bitmap fonts
in ``Fonts_client.zip``; the object templates (``Objects_client.zip`` and the expansion zips) say which minimap icon each vehicle and kit uses
(``ObjectTemplate.vehicleHud.miniMapIcon``), and ``Localization/English/english.utxt`` holds the display names.

The viewer builds its own source from them, only what it draws: ``<store>/tables.json`` (every vehicle and kit icon / name and the control
point and scoreboard strings), ``<store>/hud/<icon>.png`` for each texture that was asked for, ``<store>/fonts/<font>.png|json``. Once the
store exists the game install is not needed any more. Clients never name a file: icons are requested by a game-style path that must exist
in the archive index.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import threading
import zipfile
from typing import Dict, List, Optional, Tuple

HUD_PREFIX = "hud/texture/"
TEMPLATE_RE = re.compile(r"^\s*ObjectTemplate\.(?:create|activeSafe)\s+(\w+)\s+(\S+)", re.I)
PROP_RE = re.compile(r"^\s*ObjectTemplate\.(\w+(?:\.\w+)?)\s+(.*?)\s*$", re.I)
COLOR_CODE_RE = re.compile(r"[\x1b§]+C?\d*|[\x00-\x1f]")        # the game's inline colour codes (ESC / section sign + C1001)
STRING_RE = re.compile(r"^(\S+)\s+(.*?)\s*$")


def norm_icon(path: str) -> str:
    """``Ingame\\Vehicles\\Icons\\Minimap\\mini_Tank.tga`` -> ``ingame/vehicles/icons/minimap/mini_tank`` (the lookup key)."""
    path = path.strip().strip('"').replace("\\", "/").lower()
    return os.path.splitext(path)[0]


def parse_templates(text: str) -> Dict[str, Dict[str, str]]:
    """Template name (lower case) -> ``{property: value}`` for the HUD properties of ``.con`` / ``.tweak`` text.

    A property belongs to the template named by the closest preceding ``create`` / ``activeSafe`` line.
    """
    out: Dict[str, Dict[str, str]] = {}
    current: Optional[Dict[str, str]] = None
    for line in text.splitlines():
        match = TEMPLATE_RE.match(line)
        if match:
            current = out.setdefault(match.group(2).lower(), {"class": match.group(1)})
            continue
        if current is None:
            continue
        prop = PROP_RE.match(line)
        if prop:
            key = prop.group(1).lower()
            if key in ("vehiclehud.minimapicon", "vehiclehud.minimapiconleadersize", "vehiclehud.hudname", "vehiclehud.vehicleicon",
                       "setvehicletype"):
                current[key.split(".")[-1]] = prop.group(2).strip().strip('"')
    return {name: props for name, props in out.items() if len(props) > 1}


def parse_strings(text: str) -> Dict[str, str]:
    strings: Dict[str, str] = {}
    for line in text.splitlines():
        match = STRING_RE.match(line)
        if match:
            strings[match.group(1)] = COLOR_CODE_RE.sub("", match.group(2)).strip().strip('"')
    return strings


#: strings the viewer shows: control point names and the scoreboard / HUD words (everything else of the 20 000 game strings is left out)
STRING_KEEP = re.compile(r"^(CPNAME_|HUD_TEXT_MENU_SCORE_|HUD_TEXT_COMMANDER_TIMELEFT|HUD_HUD_KILLEDBY_|HUD_TEXT_MENU_SQUAD_|"
                         r"HUD_TEXT_MENU_SCORE|HUD_TEXT_MENU_TIME|HUD_HUD_SCOREBOARD)", re.I)
#: bitmap fonts of the HUD used by the viewer (Fonts_client.zip, English)
FONTS = ("ingameChatFontLocalOutline_8", "ingameChatFontOutline_8", "digitalNumbers", "digitalSmallNumbers", "hudFontLocalBold_9", "hudFontBold_9",
         "scoreboardFontLocal_8", "scoreboardFont_8")


#: textures drawn by the page itself (map icons, HUD frames, the scoreboard of the game)
STATIC_TEXTURES = (
    "ingame/player/icons/minimap/mini_soldier", "ingame/player/icons/minimap/mini_headingarrow", "ingame/minimap/icons/icon_uav",
    "ingame/minimap/icons/radar", "ingame/vehicles/icons/minimap/mini_airdefsmall", "ingame/vehicles/icons/minimap/mini_armourdefsmall",
    "ingame/player/icons/minimap/mini_commander", "ingame/player/icons/minimap/mini_commander1", "ingame/player/icons/minimap/mini_commander2",
    "ingame/player/icons/minimap/mini_localarrow2", "ingame/minimap/map_uav", "ingame/minimap/icons/icon_supplies",
    "ingame/minimap/icons/icon_vehicledrop", "ingame/minimap/icons/request_circle", "ingame/minimap/icons/icon_artillery",
    "ingame/minimap/icons/placedairstrike",
    "ingame/minimap/map_frameopen", "ingame/minimap/teampoint_blueleft", "ingame/minimap/teampoint_redright", "ingame/bars/timebarbackground",
    "ingame/minimap/flags_frameopen_captured_left", "ingame/minimap/flags_frameopen_captured_right",
    "ingame/scoreboard/team1_byscore", "ingame/scoreboard/team2_empty", "ingame/scoreboard/scoreboard_icons", "ingame/scoreboard/bottom",
    "ingame/scoreboard/staticinfobackground", "ingame/scoreboard/icons/icon_death", "ingame/scoreboard/icons/icon_faded",
    "ingame/scoreboard/icons/kickvote_no", "ingame/scoreboard/arrowdown",
    "ingame/flags/icons/hud/score/us/scoreboard_flag", "ingame/flags/icons/hud/score/ch/scoreboard_flag",
    "ingame/flags/icons/hud/score/mec/scoreboard_flag", "ingame/flags/icons/hud/score/eu/scoreboard_flag",
) + tuple(f"ingame/player/icons/minimap/mini_squad_{n}_small" for n in range(10)) + tuple(
    f"ingame/generalicons/ranks/rank_{n:02d}" for n in range(22)) + tuple(
    f"ingame/flags/icons/minimap/{fac}/minimap_{kind}" for fac in ("us", "ch", "mec", "eu", "neutral") for kind in ("cp", "cpbase"))


def parse_font(text: str) -> Dict[str, object]:
    """A ``.dif`` bitmap font: ``header`` (version, name, atlas width, atlas height, line height), ``glyphs`` rows
    ``code f1 f2 f3 y_offset x0 y0 x1 y1`` (x0..y1 = the glyph's rectangle in the atlas, f2 the advance) and ``kerning`` rows."""
    lines = [ln.rstrip("\r\n").split("\t") for ln in text.splitlines()]
    flat = [ln[0].strip() for ln in lines]
    try:
        width, height, line = int(float(flat[3])), int(float(flat[4])), float(flat[5])
        g0 = flat.index("glyphs") + 2
        glyphs: Dict[str, List[float]] = {}
        for row in lines[g0:]:
            if not row[0].strip().isdigit() or len(row) < 9 or row[0].strip() == "kerning":
                break
            glyphs[row[0].strip()] = [float(v) for v in row[1:9]]
        kern: Dict[str, float] = {}
        if "kerning" in flat:
            for row in lines[flat.index("kerning") + 2:]:
                if len(row) >= 3 and row[0].strip().isdigit():
                    kern[row[0].strip() + "," + row[1].strip()] = float(row[2])
    except (ValueError, IndexError):
        return {}
    return {"w": width, "h": height, "line": line, "glyphs": glyphs, "kern": kern}


class GameAssets:
    """Lazy, thread-safe view of the HUD artwork and template tables of one install, backed by a private on-disk store."""

    def __init__(self, root: Optional[str], store: Optional[str] = None):
        self.root = root
        self.mod = os.path.join(root, "mods", "bf2") if root else ""
        self.store = store
        if store:
            os.makedirs(os.path.join(store, "hud"), exist_ok=True)
            os.makedirs(os.path.join(store, "fonts"), exist_ok=True)
        self._lock = threading.Lock()
        self._hud_index: Optional[Dict[str, Tuple[str, str]]] = None      # normalised key -> (zip path, member)
        self._png: Dict[str, Optional[bytes]] = {}
        self._templates: Optional[Dict[str, Dict[str, str]]] = None
        self._strings: Optional[Dict[str, str]] = None
        self._lower: Optional[Dict[str, str]] = None

    # --- icons -------------------------------------------------------------------------------------------------------
    def _index(self) -> Dict[str, Tuple[str, str]]:
        with self._lock:
            if self._hud_index is None:
                index: Dict[str, Tuple[str, str]] = {}
                path = os.path.join(self.mod, "Menu_client.zip")
                try:
                    with zipfile.ZipFile(path) as z:
                        for name in z.namelist():
                            low = name.lower()
                            if low.startswith(HUD_PREFIX) and low.endswith((".dds", ".tga", ".png")):
                                key = norm_icon(low[len(HUD_PREFIX):])
                                if key not in index or low.endswith(".dds"):      # same art in both formats: prefer .dds
                                    index[key] = (path, name)
                except (OSError, zipfile.BadZipFile):
                    pass
                self._hud_index = index
            return self._hud_index

    def _stored(self, *parts: str) -> Optional[str]:
        return os.path.join(self.store, *parts) if self.store else None

    def has_icon(self, icon: str) -> bool:
        key = norm_icon(icon)
        path = self._stored("hud", key.replace("/", os.sep) + ".png")
        return key in self._index() or bool(path and os.path.isfile(path))

    def icon_png(self, icon: str) -> Optional[bytes]:
        """PNG bytes of a HUD texture named like the game does (any case, ``/`` or backslash, with or without extension).

        Converted once from the game's archive and kept in the store (``hud/<key>.png``); later requests need no game install.
        """
        key = norm_icon(icon)
        path = self._stored("hud", key.replace("/", os.sep) + ".png")
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                return fh.read()
        hit = self._index().get(key)
        if hit is None:
            return None
        with self._lock:
            if key in self._png:
                return self._png[key]
        data: Optional[bytes] = None
        try:
            from PIL import Image
            with zipfile.ZipFile(hit[0]) as z:
                image = Image.open(io.BytesIO(z.read(hit[1]))).convert("RGBA")
            out = io.BytesIO()
            image.save(out, "PNG", optimize=True)
            data = out.getvalue()
        except (ImportError, OSError, KeyError, ValueError, zipfile.BadZipFile):
            data = None
        with self._lock:
            self._png[key] = data
        if data and path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        return data

    # --- fonts -------------------------------------------------------------------------------------------------------
    def font(self, name: str) -> Optional[Tuple[bytes, Dict[str, object]]]:
        """``(atlas PNG, metrics)`` of one of the HUD's bitmap fonts (``FONTS``), English variant at the base resolution."""
        if name not in FONTS:
            return None
        png_path, json_path = self._stored("fonts", name + ".png"), self._stored("fonts", name + ".json")
        if png_path and json_path and os.path.isfile(png_path) and os.path.isfile(json_path):
            with open(png_path, "rb") as fh, open(json_path, encoding="utf-8") as jh:
                return fh.read(), json.load(jh)
        if not self.root:
            return None
        try:
            from PIL import Image
            with zipfile.ZipFile(os.path.join(self.mod, "Fonts_client.zip")) as z:
                members = {n.lower(): n for n in z.namelist()}
                for folder in ("english/", ""):
                    dif, dds = members.get(folder + name.lower() + ".dif"), members.get(folder + name.lower() + ".dds")
                    if dif and dds:
                        break
                else:
                    return None
                metrics = parse_font(z.read(dif).decode("latin1"))
                image = Image.open(io.BytesIO(z.read(dds))).convert("RGBA")
        except (ImportError, OSError, KeyError, ValueError, zipfile.BadZipFile):
            return None
        if not metrics:
            return None
        out = io.BytesIO()
        image.save(out, "PNG", optimize=True)
        if png_path and json_path:
            with open(png_path, "wb") as fh, open(json_path, "w", encoding="utf-8") as jh:
                fh.write(out.getvalue())
                json.dump(metrics, jh, separators=(",", ":"))
        return out.getvalue(), metrics

    # --- templates and names -----------------------------------------------------------------------------------------
    def _client_zips(self) -> List[str]:
        return sorted(glob.glob(os.path.join(self.root, "mods", "*", "*_client.zip"))) if self.root else []

    def templates(self) -> Dict[str, Dict[str, str]]:
        """Vehicle and kit HUD properties of every template found in the installed object archives."""
        with self._lock:
            if self._templates is not None:
                return self._templates
        found: Dict[str, Dict[str, str]] = {}
        for path in self._client_zips():
            if "objects" not in os.path.basename(path).lower() and "booster" not in os.path.basename(path).lower():
                continue
            try:
                with zipfile.ZipFile(path) as z:
                    for name in z.namelist():
                        low = name.lower()
                        if (low.startswith(("vehicles/", "kits/"))) and low.endswith((".con", ".tweak")):
                            found.update(parse_templates(z.read(name).decode("latin1")))
            except (OSError, zipfile.BadZipFile):
                continue
        with self._lock:
            self._templates = found
        return found

    def strings(self) -> Dict[str, str]:
        with self._lock:
            if self._strings is not None:
                return self._strings
        merged: Dict[str, str] = {}
        folder = os.path.join(self.mod, "Localization", "English")
        for name in ("english.utxt", "english_Patch.utxt", "XPenglish.utxt"):
            try:
                with open(os.path.join(folder, name), "rb") as fh:
                    merged.update(parse_strings(fh.read().decode("utf-16")))
            except (OSError, UnicodeError):
                continue
        with self._lock:
            self._strings = merged
        return merged

    def strings_for(self, keys: List[str]) -> Dict[str, str]:
        """Display text of each key that exists in the English strings (case-insensitive), e.g. ``CPNAME_DP_64_reactors`` -> Reactor Towers."""
        table = self.strings()
        with self._lock:
            if self._lower is None:
                self._lower = {k.lower(): v for k, v in table.items()}
            lower = self._lower
        return {k: lower[k.lower()] for k in keys if k.lower() in lower}

    def vehicle_info(self, template: str) -> Optional[Dict[str, Optional[str]]]:
        """``{"icon", "size", "name", "type"}`` of a vehicle template, or None when the game has no such vehicle HUD entry."""
        props = self.templates().get(template.lower())
        if not props or "minimapicon" not in props:
            return None
        icon = props["minimapicon"]
        return {"icon": norm_icon(icon) if self.has_icon(icon) else None, "size": props.get("minimapiconleadersize"),
                "name": self.strings().get(props.get("hudname", "")), "type": props.get("setvehicletype")}

    def kit_icons(self) -> Dict[str, str]:
        """Kit name (``assault``, ``support`` ...) -> minimap icon key, from the ``Kits/<team>/<TEAM>_<Kit>`` templates."""
        icons: Dict[str, str] = {}
        for name, props in self.templates().items():
            match = re.match(r"^(?:us|ch|mec|eu)_(\w+)$", name)
            if match and "minimapicon" in props and self.has_icon(props["minimapicon"]):
                icons.setdefault(match.group(1), norm_icon(props["minimapicon"]))
        return icons

    # --- the store ---------------------------------------------------------------------------------------------------
    def tables(self) -> Optional[Dict[str, object]]:
        """Everything the viewer needs by name, in one small document: ``vehicles`` (template -> icon, leader size, display name, type), ``kits``
        (kit -> icon) and ``strings`` (lower case key -> text, only the control point and scoreboard strings). Built once from the game's archives
        and kept in ``<store>/tables.json``; ``None`` when there is neither a store nor a game install."""
        path = self._stored("tables.json")
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        if not self.root:
            return None
        kit = re.compile(r"^(?:us|ch|mec|eu)_\w+$")
        vehicles = {name: info for name in self.templates() if not kit.match(name)
                    for info in [self.vehicle_info(name)] if info and (info["icon"] or info["name"])}
        strings = {key.lower(): text for key, text in self.strings().items() if STRING_KEEP.match(key)}
        doc = {"vehicles": vehicles, "kits": self.kit_icons(), "strings": strings}
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, separators=(",", ":"), ensure_ascii=False)
        return doc

    def build_store(self) -> Dict[str, int]:
        """Prepare the whole store now (tables, fonts and every texture the page can ask for) so that the first page load is instant."""
        doc = self.tables() or {}
        keys = {info["icon"] for info in doc.get("vehicles", {}).values() if info.get("icon")} | set(doc.get("kits", {}).values())
        keys |= set(STATIC_TEXTURES)
        built = sum(1 for key in sorted(keys) if self.icon_png(key))
        fonts = sum(1 for name in FONTS if self.font(name))
        return {"vehicles": len(doc.get("vehicles", {})), "strings": len(doc.get("strings", {})), "textures": built, "fonts": fonts}
