"""Development tool: bundle the game's own HUD message templates and team names.

* ``bf2demo/assets/hud_strings.json``: every English ``HUD_HUD_*``, ``GAME_MESSAGE_*``,
  ``HUD_TKPUNISH_*`` and a few ``HUD_TEXT_*`` strings (colour codes removed), e.g.
  ``HUD_HUD_KILLEDBY_KILLS`` = ``#PLAYERNAME1# [#WEAPON#] #PLAYERNAME2#``.
* ``bf2demo/assets/team_names.json``: ``gameLogic.setTeamName`` of each level's ``Init.con``.

The parser never reads game files; it uses these bundled assets.

Usage: python scripts/build_hud_text.py [mods/bf2 root]
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = re.compile(r"^(HUD_HUD_|GAME_MESSAGE_|HUD_TKPUNISH_|HUD_TEXT_MENU_CHANGED_TEAM|HUD_TEXT_CHAT_|"
                  r"AUTO_VOTING_|LOCERROR_|HUD_YOUHAVEKICKED|HUD_SQUAD_PLAYERKICKED|HUD_LEVELNAME_|HUD_TEXT_COMMANDER_|AWARD_Name_)")


def load_strings(mod_root: str):
    loc_dir = os.path.join(mod_root, "Localization", "English")
    esc = chr(27)
    color = re.compile(chr(0xA7) + r"(C\d{4}|\d)")
    line_re = re.compile(r"^(\S+?)\s*" + esc + esc + "(.*?)" + esc + esc + r"\s*$")
    texts = {}
    for name in sorted(os.listdir(loc_dir)):
        if name.lower().endswith(".utxt"):
            raw = open(os.path.join(loc_dir, name), "rb").read().decode("utf-16", errors="replace")
            for line in raw.splitlines():
                m = line_re.match(line)
                if m and KEEP.match(m.group(1)):
                    texts[m.group(1)] = color.sub("", m.group(2))
    return texts


def team_names(mod_root: str):
    out = {}
    levels = os.path.join(mod_root, "Levels")
    for level in sorted(os.listdir(levels)):
        for entry in os.listdir(os.path.join(levels, level)):
            if entry.lower() != "server.zip":
                continue
            zf = zipfile.ZipFile(os.path.join(levels, level, entry))
            for name in zf.namelist():
                if name.lower() == "init.con":
                    text = zf.read(name).decode("latin1")
                    teams = dict(re.findall(r'(?im)^\s*gameLogic\.setTeamName\s+(\d)\s+"([^"]*)"', text))
                    flags = dict(re.findall(r'(?im)^\s*gameLogic\.setTeamFlag\s+(\d)\s+"([^"]*)"', text))
                    if teams:
                        out[level.lower()] = {"1": teams.get("1"), "2": teams.get("2")}
    return out


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    root = argv[0] if argv else r"C:\Program Files (x86)\EA Games\Battlefield 2\mods\bf2"
    assets = os.path.join(ROOT, "bf2demo", "assets")
    strings = load_strings(root)
    with open(os.path.join(assets, "hud_strings.json"), "w", encoding="utf-8") as fh:
        json.dump({"doc": "English HUD message templates of the game (colour codes removed)",
                   "strings": strings}, fh, indent=0, ensure_ascii=False)
    teams = team_names(root)
    with open(os.path.join(assets, "team_names.json"), "w", encoding="utf-8") as fh:
        json.dump({"doc": "gameLogic.setTeamName of each level (team 1, team 2)", "teams": teams},
                  fh, indent=0, ensure_ascii=False)
    print(f"{len(strings)} strings, team names for {len(teams)} levels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
