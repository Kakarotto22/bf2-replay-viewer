# bf2demo - user guide (English)

`bf2demo` reads a Battlefield 2 replay (`.bf2demo`) and shows what the server announced to the players during the recording.
Requirements: Python 3.9 or newer, nothing to install. Run it from the project folder:

```
python -m bf2demo path\to\file.bf2demo [options]
```

With no options it prints the **full readable report**. Every time is `mm:ss` since the start of the recording
(the game runs at 30 ticks per second).

## 1. "I want to see ..." - which command

| I want to see | Command |
|---|---|
| Everything in a readable form | `python -m bf2demo FILE` |
| Which kinds of data this file holds and how much | `--inventory` |
| Only some parts of the report | `--report players,flags` (names: `--list-sections`) |
| Server rules (rounds, time limit, tickets, vehicles on/off ...) | `--report settings` |
| Who played, score, kills, deaths | `--scoreboard` (or `--report players`) |
| Kill feed, joins, leaves, squads, flag captures, in order | `--feed` (`--feed-verbose` adds vehicle enter/exit) |
| When each flag changed owner | `--report flags` |
| Tickets of both teams (and how the round ended) | `--report overview,teams` |
| Squads, who joined which squad and when, invitations | `--report squads` |
| UAV, supply crates, parachute drops, artillery | `--report commander` |
| Which vehicles existed, were destroyed, were entered | `--report vehicles` |
| Rockets / missiles / grenades fired | `--report weapons` |
| Where every soldier and vehicle went | `--tracks` (summary) or `--export-tracks out.csv` (every position) |
| Turret, rotor, wing angles of vehicles | `--export-parts out.csv` |
| Every single decoded event | `--events` |
| Flags, vehicle spawners and spawn points of the map | `--map-info` |
| All of it for your own program (JSON) | `--export-json out.json` (add `--json-tracks`, `--json-parts`, `--json-indent 2`) |
| A server `GamePlayObjects.con` rebuilt from the recording | `--export-con out.con` |
| Destructible bridges, crates, barrels | `--export-static out.con` |

Several options can be combined: `python -m bf2demo FILE --feed --scoreboard`.
Redirect to a file with `> report.txt` (PowerShell: `| Out-File report.txt -Encoding utf8`).

## 2. The report sections

`overview` server, map, length, round schedule - `settings` server rules - `teams` tickets - `players` scoreboard -
`flags` owner changes with time - `vehicles` - `weapons` - `radio` medic/ammo/repair/revive calls and spots per player - `squads` squad membership and invitations - `commander` UAVs, supply crates, parachute drops, artillery - `timeline` key moments - `events` event counts.

Example: `python -m bf2demo FILE --report overview,flags,timeline`

## 3. What a recording can and cannot contain

* **Contains:** players (name, team, squad, score, kills, deaths, ping, rank), kills with weapon/vehicle, flags and owners,
  tickets, every vehicle and soldier with position over time, vehicle part angles, projectiles, soldier spawn positions,
  squads/orders/commander/votes/medals, voice on/off, server settings and the map rotation.
* **Never contains:** player IP addresses (see below), CD-key hashes, passwords, the map's combat-area polygon, flag capture
  radius/times, vehicle respawn delays, text chat, buildings and terrain.

The full catalogue is in `DATA.md` (rebuild: `python scripts/build_data_doc.py > DATA.md`).

### Why are there no player IP addresses?

This is normal, also for online games. In the game protocol the server never tells the clients (or the recording) the address of
other players: the "player created" message (`CreatePlayer`) carries only the name, a slot number, the team, a bot/remote flag and
ids - checked in the server binary's constructor and reader of that event. Every bit of the recordings is decoded (100 %), so
nothing is hidden in unread data. Only the server itself (its own logs) knows the addresses.

## 4. Rebuilding a map file (`--export-con`)

```
python -m bf2demo FILE --export-con GamePlayObjects.con
python -m bf2demo FILE --export-con GamePlayObjects.con --merge OTHER1.bf2demo --merge OTHER2.bf2demo
```

A single recording shows a spawn point only if two soldiers spawned at the identical position, and an exact vehicle spawner
only if the vehicle respawned during the recording. `--merge` adds more recordings of the **same map** as evidence (measured on 92 real recordings, below). The notes at the end of the written file list what was observed and what was copied
from the original map. Useful options: `--placeholder-spawn-points`, `--drop-unobserved`, `--layout REF.con`, `--no-layout`.

## 5. JSON for programs

`--export-json out.json` writes format `bf2demo-json/2`: `demo`, `server_settings`, `map_info`, `players`, `feed`,
`scoreboard`, `tickets`, `control_points`, `objects` (and `tracks` with `--json-tracks`). Field renames since format 1 are listed in
`README.md`.

## 6. Use it from Python

```python
from bf2demo.reader import load_demo
from bf2demo.replay import build_replay

replay = build_replay(load_demo("file.bf2demo"))
print(replay.server_info["time_limit"], [p.name for p in replay.player_history])
for tick, event in replay.events:
    if event.name == "KilledBy":
        print(tick / 30, event.fields)
```

## 7. Tips

* `undecodable=0` in the first lines means the whole file was understood.
* A recording that started mid-round (not from the map load) has exact counters but some snapshot-only data (see `DATA.md`).
* Tests: `python -m unittest discover -s tests -t .`

## 8. Measured: what `--merge` gains (BF2RANGERS recordings, 2 days)

Spawn points found (two soldiers at the identical position), best single recording -> all recordings of that map merged;
"hit" = the point exists in the original map file:

| map | recordings | single | merged | hits (merged) |
|---|---|---|---|---|
| road_to_jalalabad | 3 | 15 | 21 | 21 of 21 |
| wake_island_2007 | 3 | 14 | 17 | 17 of 17 |
| gulf_of_oman | 4 | 28 | 35 | 22 of 35 |
| zatar_wetlands (custom) | 4 | 34 | 40 | 0 (the custom map moved its flags) |

More recordings of the same map add spawn points and never remove or change one.
In the custom Zatar map a single recording gave 4 observed spawn points, the merge of five gave 40.

## 9. Radio and chat
Radio-style calls reach a recording as HUD events: `--report radio` (or `--feed-verbose`) shows medic/ammo/repair/revive calls,
automatic revive calls and spotted units per player. The separate `RadioMessage` event and free-text chat never appear in any of the
recordings examined (92 from two days, 32 of them with human players, plus the older samples); in the server binary chat is sent as a
string message on the connection, not as one of the 63 game events the recorder stores.

## 10. The end of a round
The recorder stops when the round ends, so the `EndOfRound` event is never stored. The report's `Ending` line infers it: when the
recording stops with one team at 30 tickets or less and falling, it shows both ticket counts and how many flags the other team held
(example: Wake Island 2026-10-13 22:48, CH at 5 tickets, US holding 6 of 6 flags).

