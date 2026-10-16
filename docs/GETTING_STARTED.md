# Getting started

Arabic: [GETTING_STARTED.ar.md](GETTING_STARTED.ar.md). Everything the parser prints and exports: [USAGE.en.md](USAGE.en.md).

## 0. What you need

| | needed for |
|---|---|
| Python 3.10 or newer | everything |
| `.bf2demo` recordings | everything (see section 1) |
| Flask and Pillow (`pip install -e ".[web]"`) | the browser viewer (the terminal parser needs nothing) |
| **Your own copy of Battlefield 2** | the game's icons, fonts and minimaps in the viewer (optional, section 2) |

```bash
git clone https://github.com/Kakarotto22/bf2-replay-viewer.git
cd bf2-replay-viewer
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[web]"
```

## 1. Get recordings

* **On your own server:** put `sv.autoRecord 1` in the server settings (one `.bf2demo` per map, written when the round ends), or start and
  stop by hand with the admin console: `demo.recordDemo <name>` / `demo.stopRecording` (it fails silently if the file name already exists).
* **Existing files:** any `.bf2demo` you already have, for example from a server operator who shares the recordings of their rounds.
* Do not publish recordings of other people's matches: they contain player names (see [NOTICE.md](../NOTICE.md)).

## 2. Fetch the game artwork (assets)

The viewer never ships EA's files. It builds a **small private store from your own installed copy** the first time it needs it.

1. Install Battlefield 2 (any normal install; under Wine / Proton also works). The viewer looks in
   `C:\Program Files (x86)\EA Games\Battlefield 2`, `C:\Program Files\EA Games\Battlefield 2`, or the folder in the environment variable
   `BF2_GAME_ROOT` (the folder that contains `mods/bf2/Levels`):

   ```bash
   export BF2_GAME_ROOT="/path/to/Battlefield 2"        # Windows PowerShell: $env:BF2_GAME_ROOT = "D:\Games\Battlefield 2"
   ```
2. Build the store once (optional, it also happens on first use):

   ```bash
   bf2view --build-assets
   ```

   It reads the game's `Menu_client.zip`, `Fonts_client.zip`, the object templates and `Localization/English/english.utxt`, and writes only what the
   page draws (about 0.3 MB of icons and fonts, plus the minimap and facts of each level you open) to `~/.bf2demo-viewer-cache/game/`. After that the
   game folder is not needed again. Change the place with `--cache DIR`.
3. **Never publish that cache folder** and never commit it (it holds EA's artwork). A public server should run without the game installed.

No install? The viewer still works: a grid sized to the recorded positions, plain shapes instead of icons, system fonts.

### Sharper maps (optional)

The game's own minimap is 512 px. Community packs render the levels in higher detail, for example the *High Definition Minimap* pack on ModDB
(8192 px). Download it from its author (not mirrored here), then:

```bash
python scripts/import_hd_maps.py path/to/HighDefinitionMinimap.zip     # converts to 4096 px JPEGs in <cache>/hd_maps/
```

Or drop your own `<level>.jpg` into a folder and pass `--maps FOLDER`. On a phone the detailed map loads only when you switch on
*More options > Detailed map*.

## 3. Use it

**Terminal** (details in [USAGE.en.md](USAGE.en.md)):

```bash
bf2demo round.bf2demo                       # the full readable report
bf2demo round.bf2demo --feed                # kill feed, joins, captures in order
bf2demo round.bf2demo --scoreboard          # who scored what
bf2demo round.bf2demo --export-json out.json
bf2demo round.bf2demo --clip out.bf2demo --clip-start 120 --clip-end 180    # cut a scene to open in the game
```

**Browser:**

```bash
bf2view --demos recordings --port 8080      # --demos can be repeated, folders are searched recursively
```

Open <http://127.0.0.1:8080/>. A recording is parsed once in the background (seconds for a short one, about 3 minutes for a 2-hour
79-player round) and cached, so the next visit is instant. Controls: **Space** play / pause, **← →** seek (Shift = 60 s), **+ / -** speed,
**F** follow the selected player, **Tab** scoreboard. Deep links: `#/demo/<id>?t=<seconds>&p=<player id>&z=<zoom>`.

**Phone:** open the address of your PC or server; the layout switches by itself under 800 px: map on top, panels below, pinch to zoom, tap a unit
for its name.

## 4. Put it online

See [deploy/README.md](../deploy/README.md): systemd + Caddy / nginx on Linux, a password for a private beta, `BF2VIEW_*` settings (uploads off by
default), and the support button (`BF2VIEW_DONATE_TELEGRAM`). Publish **without** the game's artwork unless you are sure you may show it.

## 5. Troubleshooting

| symptom | what to do |
|---|---|
| The page shows an old version | hard refresh (Ctrl+F5); the viewer revalidates its files, but a proxy may cache them |
| Grid instead of the map | no game install found: set `BF2_GAME_ROOT`, then `bf2view --build-assets` |
| A custom map shows a grid | expected: custom levels have no stock minimap; give `--maps` an image named `<level>.jpg` |
| First open of a long round is slow | it is being parsed once; wait, or open it later |
| Port already in use | `--port 8081`; stop the old server first (it keeps old code in memory) |
| Need to start over | delete `~/.bf2demo-viewer-cache` |

## 6. Develop

```bash
python -m unittest discover -s tests -t .        # tests that need a missing recording are skipped
```

How to add an event layout, a report section or a catalogue entry: the *Extending* section of the [README](../README.md). Rules for
contributions (no game content, no real player names): [CONTRIBUTING.md](../CONTRIBUTING.md).
