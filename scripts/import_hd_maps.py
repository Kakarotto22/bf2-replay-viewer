"""Convert the "High Definition Minimap" pack (8192x8192 DXT1 ``ingameMap.dds`` per level) into JPEGs for the web viewer.

The pack is a game mod: it is not installed into the game here. Each image becomes ``<cache>/hd_maps/<level>.jpg`` (lower case level name, what
``python -m bf2demo.web`` looks for before it builds its own detailed map). When the level is installed, the converted picture is compared with the
level's own minimap (greyscale correlation, same extent assumed) so a wrongly aligned or different map is reported instead of used silently.

Usage::

    python scripts/import_hd_maps.py external_assets/hd_minimap/HighDefinitionMinimap.zip [--size 4096] [--cache DIR] [--level dalian_plant]
"""

from __future__ import annotations

import argparse
import io
import math
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bf2demo.web import maps  # noqa: E402


def correlation(a, b) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def stock_minimap(level: str):
    """The level's own 512 px minimap as a PIL image, or None."""
    from PIL import Image
    root = maps.game_root()
    level_dir = maps._level_dir(root, level) if root else None
    if not level_dir:
        return None
    try:
        with zipfile.ZipFile(os.path.join(level_dir, "client.zip")) as z:
            return Image.open(io.BytesIO(maps._read(z, "Hud/Minimap/ingameMap.dds"))).convert("L")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def main(argv=None) -> int:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pack", help="HighDefinitionMinimap.zip")
    ap.add_argument("--size", type=int, default=4096, help="output size in pixels (default 4096)")
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".bf2demo-viewer-cache"))
    ap.add_argument("--level", help="convert only this level (folder name, any case)")
    args = ap.parse_args(argv)
    out_dir = os.path.join(args.cache, "hd_maps")
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(args.pack) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            match = re.match(r"^[^/]+/([^/]+)/ingameMap\.dds$", info.filename, re.I)
            if not match:
                continue
            name = match.group(1)
            if args.level and name.lower() != args.level.lower():
                continue
            image = Image.open(io.BytesIO(z.read(info))).convert("RGB")
            small = image.resize((args.size, args.size), Image.LANCZOS)
            target = os.path.join(out_dir, name.lower() + ".jpg")
            small.save(target, "JPEG", quality=args.quality, optimize=True)
            note = "level not installed"
            stock = stock_minimap(name)
            if stock is not None:
                corr = correlation(list(image.convert("L").resize((128, 128), Image.BOX).getdata()),
                                   list(stock.resize((128, 128), Image.BOX).getdata()))
                note = f"correlation with the installed minimap {corr:.3f}" + ("" if corr >= 0.9 else "  <-- DIFFERENT OR MISALIGNED, check before use")
            print(f"{name:26s} -> {target} ({os.path.getsize(target) / 1e6:.1f} MB)  {note}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
