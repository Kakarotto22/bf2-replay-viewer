# How the screenshots are made (and how to make yours)

The pictures in `docs/img/` were taken from the real viewer with **the author's own copy of Battlefield 2 installed**, so the viewer could build its
asset store and draw the game's minimap, icons, fonts and HUD. Without the game the same page looks like the two `noassets-*` pictures (a grid, plain
shapes). You get the full look the same way:

## 1. Give the viewer your assets

```bash
export BF2_GAME_ROOT="/path/to/Battlefield 2"       # PowerShell: $env:BF2_GAME_ROOT = "C:\Games\Battlefield 2"  (skip when it is in Program Files)
bf2view --build-assets                              # builds ~/.bf2demo-viewer-cache/game (about 0.3 MB; see GETTING_STARTED.md)
```

Optional for the sharpest maps: the *High Definition Minimap* pack (`scripts/import_hd_maps.py`, see [GETTING_STARTED.md](GETTING_STARTED.md)).

## 2. Start the viewer on a few recordings and let it parse them

```bash
bf2view --demos recordings --port 8080 --no-upload
# open http://127.0.0.1:8080/ once, click each recording: it is parsed in the background and cached (a long round takes a few minutes)
```

## 3. Take the pictures

`scripts/screenshot.py` drives a headless Edge / Chrome (`pip install aiohttp`). A recording's address is `#/demo/<id>`; copy it from the browser,
and add the deep-link parameters you want: `t` = seconds from the start, `board=1` opens the scoreboard, `z` = zoom, `p` = player id, `?lang=ar` = Arabic.

```bash
URL="http://127.0.0.1:8080/#/demo/ID_OF_THE_RECORDING"
python scripts/screenshot.py "$URL?t=900"            docs/img/viewer-desktop.png --size 1440x900
python scripts/screenshot.py "$URL?t=1500&board=1"   docs/img/scoreboard.png
python scripts/screenshot.py "http://127.0.0.1:8080/#/" docs/img/library.png --size 1440x760
python scripts/screenshot.py "$URL?t=900"            docs/img/viewer-phone.png --phone          # a real emulated 390 x 844 phone
python scripts/screenshot.py "http://127.0.0.1:8080/?lang=ar#/demo/ID?t=1200" docs/img/viewer-phone-ar.png --phone
```

Tips: use `--wait 25` for a long round; pick a moment with action by scrubbing the timeline in the browser first and reading the time from the clock;
the `noassets-*` pictures were made the same way with the game folder hidden (`BF2_GAME_ROOT` pointing nowhere and no install in `Program Files`).

## A note on rights

The pictures show the game's own artwork (minimap, icons, HUD) next to player nicknames from public community rounds. They illustrate the tool and
are not covered by the MIT license; if you are a rights holder or a player shown and want one removed or blurred, open an issue (see [NOTICE.md](../NOTICE.md)).
