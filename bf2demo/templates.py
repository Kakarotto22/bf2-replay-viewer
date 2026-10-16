"""Canonical asset access: object templates, per-level definitions, names.

All data is read from the bundled ``assets/canonical_assets.json`` so the
parser is fully standalone. Nothing here touches the game installation.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict, List, Optional

_ASSETS_PATH = os.path.join(os.path.dirname(__file__), "assets", "canonical_assets.json")


@lru_cache(maxsize=1)
def load_assets(path: Optional[str] = None) -> dict:
    """The bundled tables; a public checkout leaves them out (names and level data of the game): the readers then fall back to the template key."""
    if path is None and not os.path.isfile(_ASSETS_PATH):
        return {"levels": {}, "localization": {}}
    with open(path or _ASSETS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def normalize_level(name: str) -> str:
    """Map a demo's level string to a canonical asset key."""
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def level_definition(map_name: str, assets: Optional[dict] = None) -> Optional[dict]:
    assets = assets or load_assets()
    return assets["levels"].get(normalize_level(map_name))


def gamemodes(level_def: dict) -> Dict[str, dict]:
    return level_def or {}


def category_rules() -> List[List]:
    """Ordered ``(category, substrings)`` vehicle classification rules.

    Sourced from the immutable template metadata in ``canonical_assets.json``.
    """
    return load_assets().get("vehicle_categories") or []


def available_sizes(mode_def: dict) -> List[str]:
    return sorted(mode_def.keys(), key=lambda s: int(s))


def vehicle_name(template: str, assets: Optional[dict] = None) -> Optional[str]:
    assets = assets or load_assets()
    return assets["localization"].get(template)


def resolve_display_name(template: str, assets: Optional[dict] = None) -> str:
    """Resolve a template key (e.g. ``tnk_type98``) to its display name.

    Vehicle archetype immutability: resolution depends only on the template
    key, never on any occupant or attacker team.
    """
    name = vehicle_name(template, assets)
    return name if name else template


@lru_cache(maxsize=1)
def _localization_keys() -> tuple:
    loc = load_assets()["localization"]
    return tuple(sorted(loc, key=len, reverse=True))


def resolve_vehicle_name(template: str, assets: Optional[dict] = None) -> Optional[str]:
    """Resolve a Refractor vehicle template (e.g. ``xpak2_tnkl2a6``) to its
    localized display name by matching a localization key against the template
    name suffix (``t90`` -> ``T-90S 'MBT'``)."""
    assets = assets or load_assets()
    loc = assets["localization"]
    low = template.lower()
    for key in _localization_keys():
        if low.endswith(key.lower()):
            return loc[key]
    return loc.get(template) or loc.get(template.lower())
