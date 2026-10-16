"""Map backdrops for the viewer, read from the player's own game install (never bundled or committed).

The minimap is ``Hud/Minimap/ingameMap.dds`` of ``Levels/<map>/client.zip``; the world extent comes from the level's
``Heightdata.con`` (primary heightmap: size N, scale s -> (N - 1) * s metres, centred on the origin).
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from typing import Dict, Optional

DEFAULT_ROOTS = [r"C:\Program Files (x86)\EA Games\Battlefield 2", r"C:\Program Files\EA Games\Battlefield 2"]


def game_root() -> Optional[str]:
    for root in [os.environ.get("BF2_GAME_ROOT")] + DEFAULT_ROOTS:
        if root and os.path.isdir(os.path.join(root, "mods", "bf2", "Levels")):
            return root
    return None


def _level_dir(root: str, level: str) -> Optional[str]:
    levels = os.path.join(root, "mods", "bf2", "Levels")
    for name in os.listdir(levels):
        if name.lower() == level.lower() and os.path.isdir(os.path.join(levels, name)):
            return os.path.join(levels, name)
    return None


def _read(z: zipfile.ZipFile, name: str) -> bytes:
    """Archive member by case-insensitive name (levels differ: ingameMap.dds / ingamemap.dds)."""
    lower = {n.lower(): n for n in z.namelist()}
    return z.read(lower[name.lower()])


def world_size(level_dir: str) -> Optional[float]:
    try:
        with zipfile.ZipFile(os.path.join(level_dir, "server.zip")) as z:
            text = _read(z, "Heightdata.con").decode("latin1")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    match = re.search(r"addHeightmap Heightmap 0 0\s+heightmap\.setSize (\d+) \d+\s+heightmap\.setScale ([\d.]+)/", text)
    return (int(match.group(1)) - 1) * float(match.group(2)) if match else None


def uncapturable_points(level: str) -> list:
    """Lower case control point template names with ``ObjectTemplate.unableToChangeTeam 1`` (main bases, carriers) in the installed level.

    The property lives only in the server's ``GamePlayObjects.con`` (it is not replicated), so it is read from the game files; custom maps
    and machines without the game give an empty list (every flag then looks capturable).
    """
    root = game_root()
    level_dir = _level_dir(root, level) if root else None
    if not level_dir:
        return []
    names = set()
    try:
        with zipfile.ZipFile(os.path.join(level_dir, "server.zip")) as z:
            for member in z.namelist():
                if not member.lower().endswith("gameplayobjects.con"):
                    continue
                current = None
                for line in z.read(member).decode("latin1").splitlines():
                    line = line.strip()
                    create = re.match(r"ObjectTemplate\.create\s+ControlPoint\s+(\S+)", line, re.I)
                    if create:
                        current = create.group(1).lower()
                    elif current and re.match(r"ObjectTemplate\.unableToChangeTeam\s+1", line, re.I):
                        names.add(current)
    except (OSError, zipfile.BadZipFile):
        return []
    return sorted(names)


def ticket_rules(level: str) -> Optional[Dict[str, object]]:
    """The conquest ticket bleed parameters of an installed level, the inputs of ``updateTicketLoss`` in the server's ``gpm_cq.py``:

    * ``loss`` / ``loss_end``: ``gameLogic.setTicketLossPerMin <team> n`` and ``setTicketLossAtEndPerMin n`` of the level's ``Init.con``;
    * ``areas["gpm_cq/64"]``: control point template (lower case) -> ``[areaValueTeam1, areaValueTeam2]`` of that game mode and size.

    A team loses ``loss[team] * (area held by the other side - area held by itself) / 100`` tickets a minute while the other side holds an
    area of at least 100 and more than it does. ``None`` when the level is not installed.
    """
    root = game_root()
    level_dir = _level_dir(root, level) if root else None
    if not level_dir:
        return None
    rules: Dict[str, object] = {"loss": {}, "loss_end": None, "areas": {}}
    try:
        with zipfile.ZipFile(os.path.join(level_dir, "server.zip")) as z:
            for member in z.namelist():
                low = member.lower().replace("\\", "/")
                text = z.read(member).decode("latin1", errors="replace")
                if low == "init.con":
                    for team, value in re.findall(r"(?im)^\s*gameLogic\.setTicketLossPerMin\s+(\d)\s+(\d+)", text):
                        rules["loss"][team] = int(value)                      # type: ignore[index]
                    match = re.search(r"(?im)^\s*gameLogic\.setTicketLossAtEndPerMin\s+(\d+)", text)
                    rules["loss_end"] = int(match.group(1)) if match else None
                elif low.endswith("/gameplayobjects.con") and low.startswith("gamemodes/"):
                    areas: Dict[str, list] = {}
                    current = None
                    for line in text.splitlines():
                        create = re.match(r"\s*ObjectTemplate\.create\s+ControlPoint\s+(\S+)", line, re.I)
                        if create:
                            current = create.group(1).lower()
                            continue
                        value = re.match(r"\s*ObjectTemplate\.areaValueTeam([12])\s+(\d+)", line, re.I)
                        if value and current:
                            areas.setdefault(current, [0, 0])[int(value.group(1)) - 1] = int(value.group(2))
                    rules["areas"]["/".join(low.split("/")[1:3])] = areas       # type: ignore[index]
    except (OSError, zipfile.BadZipFile):
        return None
    return rules


def load_backdrop(level: str) -> Optional[Dict[str, object]]:
    """``{"png": bytes, "world_size": metres}`` or None when the game or the level is not installed."""
    root = game_root()
    level_dir = _level_dir(root, level) if root else None
    if not level_dir:
        return None
    size = world_size(level_dir)
    try:
        from PIL import Image
        with zipfile.ZipFile(os.path.join(level_dir, "client.zip")) as z:
            image = Image.open(io.BytesIO(_read(z, "Hud/Minimap/ingameMap.dds"))).convert("RGB")
    except (ImportError, OSError, KeyError, zipfile.BadZipFile):
        return None
    out = io.BytesIO()
    image.save(out, "PNG")
    return {"png": out.getvalue(), "world_size": size}


# ----------------------------------------------------------------------------------------------------------------------
# High resolution map: the terrain colour tiles of the level (``Colormaps/txAAxBB.dds``, 512 px each, 0.5 m per pixel on a 2 km map)
# stitched together and added, as detail, to the game's minimap. The tile grid follows the heightmap: column = A (west to east), row =
# B counted from the south (checked: the tiles that do not exist are the low-lying water tiles under this layout, not under the flipped one); each tile
# image is stored upside down.

DETAIL_GAIN = 0.75        # share of the tiles' high-frequency detail added to the minimap (the painted decals are exaggerated)


def hd_map(level: str, max_size: int = 4096, quality: int = 88) -> Optional[bytes]:
    """JPEG bytes of the stitched, hillshaded terrain (north up, world centred), or None when the level has no colour tiles."""
    root = game_root()
    level_dir = _level_dir(root, level) if root else None
    if not level_dir:
        return None
    try:
        from PIL import Image, ImageChops, ImageFilter
        with zipfile.ZipFile(os.path.join(level_dir, "client.zip")) as z:
            lower = {n.lower(): n for n in z.namelist()}
            found = {}
            for name in lower:
                match = re.fullmatch(r"colormaps/tx(\d\d)x(\d\d)\.dds", name)
                if match:
                    found[(int(match.group(1)), int(match.group(2)))] = lower[name]
            if not found:
                return None
            # a tile covers 256 m; the outermost tiles are often missing (open water), so the grid comes from the world size
            extent = world_size(level_dir)
            grid = max(max(max(a, b) for a, b in found) + 1, int(round(extent / 256)) if extent else 0)
            first = Image.open(io.BytesIO(z.read(next(iter(found.values())))))
            tile = first.width
            canvas = Image.new("RGB", (grid * tile, grid * tile))
            for (a, b), member in found.items():
                canvas.paste(Image.open(io.BytesIO(z.read(member))).convert("RGB").transpose(Image.FLIP_TOP_BOTTOM), (a * tile, (grid - 1 - b) * tile))
        # tiles that do not exist (open water) take the mean colour of the real ones: a flat fill adds no detail and, unlike a dark
        # constant, leaves no halo along the coast when the blur is subtracted
        from PIL import ImageStat
        present = Image.new("L", (grid, grid), 0)
        for a, b in found:
            present.putpixel((a, grid - 1 - b), 255)
        small = canvas.resize((grid * 8, grid * 8), Image.BOX)
        mean = tuple(int(v) for v in ImageStat.Stat(small, mask=present.resize(small.size, Image.NEAREST)).mean)
        for a in range(grid):
            for b in range(grid):
                if (a, b) not in found:
                    canvas.paste(mean, (a * tile, (grid - 1 - b) * tile, (a + 1) * tile, (grid - b) * tile))
        # the game's own minimap carries the lighting, water and colour grading but only 4 m per pixel; the colour tiles carry the detail
        # (roads, paths, field boundaries) at 0.5 m per pixel. The result is the minimap plus the high-frequency part of the tiles.
        with zipfile.ZipFile(os.path.join(level_dir, "client.zip")) as z:
            base = Image.open(io.BytesIO(_read(z, "Hud/Minimap/ingameMap.dds"))).convert("RGB").resize(canvas.size, Image.BICUBIC)
        detail = ImageChops.subtract(canvas, canvas.filter(ImageFilter.GaussianBlur(tile / 64)), scale=1, offset=128)
        gain = [max(0, min(255, 128 + int(round((v - 128) * DETAIL_GAIN)))) for v in range(256)]
        detail = detail.point(gain * 3)
        # open water carries no real detail (the sea floor texture shows up as noise and as a dark halo along the coast): fade it out
        r, g, b = base.split()
        water = ImageChops.multiply(ImageChops.subtract(b, r).point(lambda v: 255 if v > 14 else 0), r.point(lambda v: 255 if v < 110 else 0))
        water = water.filter(ImageFilter.GaussianBlur(tile / 24))
        detail = Image.composite(Image.new("RGB", detail.size, (128, 128, 128)), detail, water)
        canvas = ImageChops.add(base, detail, scale=1, offset=-128)
        if canvas.width > max_size:
            canvas = canvas.resize((max_size, max_size), Image.LANCZOS)
        out = io.BytesIO()
        canvas.save(out, "JPEG", quality=quality, optimize=True)
        return out.getvalue()
    except (ImportError, OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
