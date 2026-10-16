# Notice, disclaimer and what is (not) in this repository

**This is an unofficial fan project.** It is not made, endorsed, sponsored or supported by Electronic Arts Inc. (EA), DICE or any of
their licensors. *Battlefield*, *Battlefield 2* and the names of its maps, vehicles and weapons are trademarks or property of EA and its
licensors. They are used here only to say what the software works with.

## 1. No game content is distributed

This repository contains **no** textures, icons, fonts, minimaps, models, sounds, level files, localisation files or executables of
Battlefield 2, and no output of a disassembler or decompiler. The browser viewer draws the game's own icons, fonts and minimaps **from your own
legally owned copy of the game**: it reads them on your machine at run time and keeps them in a local cache folder (`~/.bf2demo-viewer-cache`).

* Do not upload, share or publish that cache folder, and do not commit it.
* A viewer that other people can reach should not serve those files: keep the game install off that machine, or publish without the asset
  store (see `deploy/README.md`, `--no-assets`). Without them the viewer still works (grid instead of a map, plain shapes instead of icons).
* The screenshots in `docs/img/` were taken with the author's own copy of the game: they show its minimap art and HUD icons (and player nicknames of
  public community rounds) to illustrate the tool. They are not under the MIT license and are removed or blurred on request (see `docs/SCREENSHOTS.md`).
* Optional third-party map packs (for example the *High Definition Minimap* pack on ModDB) are not included and not mirrored. Download them
  from their authors if you want them, and respect their terms.

## 2. Small data tables derived from the game (`bf2demo/assets/`)

A parser cannot work without knowing which number means which object. These small tables hold identifiers and short names, written down
from the game's programs for **interoperability** with recordings you own:

| file | content |
|---|---|
| `templates.json.gz` | object template ids, names and class sequence (what a template id in a recording means) |
| `event_names.json`, `settle_offsets.json`, `world_sizes.json`, `weapon_slots.json`, `team_names.json` | event names, numeric facts and name tables |
| `hud_strings.json`, `hud_names.json` | the short English text patterns and vehicle / weapon display names the game prints in its kill log |

The game's level files (`GamePlayObjects.con` layouts) and the per-level definition tables are **not** shipped. For exact exports give your
own layout: `--export-con OUT --layout YOUR_GamePlayObjects.con`. The scripts `scripts/build_*.py` rebuild the tables from your install.

If you are a rights holder and want any of these tables removed or replaced, open an issue or contact the maintainer (section 6): it will be
done promptly.

## 3. How the format was learned

The `.bf2demo` format was worked out from the game's own programs on lawfully obtained copies, to read and convert recordings of matches the
user took part in or hosted. No binary, no decompiled code and no key material is published here and none may be contributed.

## 4. Recordings and privacy

A recording lists the names of the players of the match. The recordings in `samples/` were made on the maintainer's own test server (bots and
test accounts). **Do not add recordings of other people's servers to a public repository or a public viewer without the players' and the server
owner's permission.** The viewer never shows IP addresses (recordings do not contain them).

## 5. No warranty

The software is provided as is (see `LICENSE`). Clips exported for the game's replay player may not play in every game version: test them
before relying on them.

## 6. Contact

Questions, rights-holder requests and privacy requests: @Thanks_Telegram, or the issue tracker of the repository.
