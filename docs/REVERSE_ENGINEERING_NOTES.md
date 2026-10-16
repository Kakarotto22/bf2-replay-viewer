<!-- Maintainer's working notes: verified wire-format facts and how they were checked. -->
# BF2 demo reverse engineering


## Sources of truth (in priority order)

1. **`extracted_bin/bf2_ia32`** — Linux dedicated server 1.5.3153.0, ELF with a
   full `.symtab` (C++ symbols such as `dice::hfe::KilledByEvent::deSerialize`).
   This is the primary reference: names are present, so start here.
2. **`extracted_bin/BF2.exe`** — Windows client, stripped. Use it for anything
   the server never does (demo *playback*/recording paths, client-only
   events, camera/HUD). Locate functions by matching strings, constants, and
   call structure found first in `bf2_ia32`.
3. **Game install** `C:\Program Files (x86)\EA Games\Battlefield 2` (override
   with `BF2_GAME_ROOT`): `mods/bf2/Levels/*/server.zip` (`.con` files,
   `GamePlayObjects.con`), `mods/bf2/Objects_server.zip`, localisation
   `.utxt`. Read-only; never write into the install.
4. **`samples/*.bf2demo`** — ground truth for validation. Small files
   (`test*`, `cp_test*`, `test_dalian32`, `test_kubra16`, `customTara`) are
   controlled experiments; `bf2rangers00*`, `zxc` are full rounds.
   `samples/zxc.target.ocr.from.game.correct.result.txt` is the in-game kill
   feed for `zxc.bf2demo` (`killer [weapon] victim`) — the acceptance test for
   kill decoding.

Tool paths: see `sources.txt`. Ghidra actually installed and used by REA is
`<ghidra install folder>` (headless: `support\analyzeHeadless.bat`).

## Workflow

1. **Question first.** State the exact unknown (e.g. "bit layout of EID 30
   ArtilleryEvent", "what follows the header strings").
2. **Find it in `bf2_ia32`.**
   - Symbols: `python scripts/dump_syms.py extracted_bin/bf2_ia32 <keyword>...`
   - Decompile: REA MCP tools if connected (see the `reverse-engineer-anything`
     skill), otherwise Ghidra headless with
     `scripts/ghidra/DumpDecomp.java <outPath> <selector,...>` (selectors are
     name substrings, `=ExactName`, or `0x` addresses). Keep the Ghidra
     project (`*.rep`, `*.gpr`, gitignored) in the scratchpad or outside the
     repo so analysis is reused, not redone.
   - Follow `deSerialize` → `BitStream::read*` calls; record field order,
     bit widths, conditionals, and the `this+0xNN` member each field lands in.
3. **Cross-check in `BF2.exe`** when the behaviour is client-side or when
   server and client could differ.
4. **Validate on samples.** Write/extend a probe in `scripts/` that decodes
   the field across *all* samples. A layout is verified only when it
   consumes packets exactly (no leftover/overrun bits) and values are sane
   (positions inside the map, ids matching CreatePlayer/CreateObject).
5. **Promote to `bf2demo/`.** Only verified layouts go into the package.
   Cite the source function and offsets in a comment, matching the style in
   `bf2demo/events.py`. Unverified/empirical findings stay in `scripts/` or
   are explicitly marked `# empirical, unverified`.
6. **Record evidence** for each claim: binary + function/address, sample(s)
   that confirm it, and any remaining doubt.

## Known format facts (already verified — do not re-derive)

- Container: Zlib stream → `int32` engine version + three length-prefixed
  strings → packets framed `<ii` (tick, payload_length) + payload
  (`bf2demo/reader.py`). Truncated recordings are salvaged.
- Each payload is exactly one network packet as built by
  `ClientConnection::transmitMsgs` and stored by
  `DemoRecorder::writeFakePacketData` (via `GameServer::flushDemoPackets`).
  Layout (`bf2demo/packet.py`): PlayerActionManager `present(1)` (always 0)
  → GameEventManager `present(1) count(8) seq(5) flag(1)` + events →
  GhostManager `present(1) time(32) count(8) hasControl(1)` + records
  `action(2) id(16)` [action 1: `isNew(1) len(13)` + `len` bits state].
  Verified: 373,828/373,829 packets across all samples consumed to the final
  padding byte (the one failure is the last packet of a corrupt zlib stream).
- Bitstream is LSB-first (`bf2demo/bitstream.py`).
- Event id is 7 bits (`width_for(69)`); all 63 registered `deSerialize`
  layouts are in `bf2demo/events.py`. Events have no length prefix.
- `DataBlockEvent` header = `kind(32) length(32)`; kind 0 server settings,
  2 current game (mode), 5 map rotation (`count`, then `str16 level, str16
  mode, u16 size`).
- Template ids are sequential `ObjectTemplateManager::createTemplate`
  counters, not hashes. `scripts/build_templates.py` reproduces the order
  (`bf2demo/assets/templates.json`); the global block is exact, the level
  `GamePlayObjects` block is aligned on the control-point block in the demo
  (`bf2demo/templatedb.py`). Unexplained: a 2–16 template per-level gap.
- Ghost id == `CreateObjectEvent.object_id`. `ControlPointNetworkable`
  layout is in `bf2demo/networkables.py`; a control point is *proven* when
  every one of its ghost updates decodes to exactly the record length.

## Recovering GamePlayObjects.con from a demo (`--export-con`)

- Exact creation transform (3 decimals) crosses the wire for every object created
  **after** recording starts: vehicles, flags. Mobile vehicles in the join snapshot
  have already settled (Y +0.6..0.9, pitch/roll) -> exported as `approx`; static
  ones (`hasMobilePhysics 0`) and flags are exact even in the snapshot.
- ObjectSpawners/SpawnPoints are server-only. Spawners are rebuilt from the vehicles
  they create (team slot = `CreateObject.team` or the owner of the bound control
  point at creation time). SpawnPoints = soldier spawns (`CreateKitEvent.position`)
  repeated >= 2 times at the same XZ; final spawn position is exact, the split of
  Y into `absolutePosition` + `setSpawnPositionOffset` (1.25 or default 1.02) is not.
- Not on the wire: control point ids/radius/timers, spawner delays, SpawnPoint
  rotation, CombatArea, the other team's vehicle of a spawner whose CP never changed hands.
- `CreateSpawnGroup` is NOT a SpawnPoint: ids 1..N are per-control-point spawn groups,
  192+ are squad groups (8-bit minimap coordinates).
- Coop bots do not produce `CreateKitEvent`; real players are needed for SpawnPoints.
- `scripts/compare_con.py GENERATED REFERENCE` is the semantic diff used for validation;
  `scripts/line_diff.py` gives the line-level identical ratio.
- Output mirrors the retail layout (CRLF, section order, 3-space indent inside `if v_arg1 == host`,
  `endIf`); headers read `... (bf2demo parser) ...`; every note is after the body (`rem ****
  bf2demo parser notes ****`) so line positions stay comparable in a diff tool.
- **Static text comes from a bundled layout**: `bf2demo/assets/layouts.json.gz` = the retail
  GamePlayObjects.con of every level/mode/size (built by `scripts/build_layouts.py`, 134 files,
  540 KB; parsed losslessly by `bf2demo/layouts.py`). The exporter re-emits it character for
  character and replaces only values the demo observed (positions, rotations, flag team, vehicle
  per team slot); layout objects the demo never showed are kept unchanged (listed in the notes;
  `--drop-unobserved` removes them); demo-only objects are added in retail style. Matching:
  position within 3 m (spawners/flags, flags also by name), X/Z within 0.0015 (spawn points),
  else same control point + same observed vehicles. `--layout FILE` uses your own file as the layout
  (e.g. the original of a custom map), `--no-layout` generates names/order.
- Result vs retail files: 4 of 7 test demos differ ONLY in numbers and the 3 header suffixes
  (98-99% identical lines). Rotation text is kept when equivalent (-180 vs 180).
  Unmatched mobile vehicles of a recording that began after tick 300 are not exported as new
  spawners (they were probably driven away).
- Other flags: `--author`, `--cp-ids` (no-layout mode), `--min-spawn-count N`, `--include-single`, `--layer N`.
- ObjectTemplate.team of a control point = owner when the recording started (mid-round recordings differ
  from the level's initial teams). Default SpawnPoint offset is 1.02 (explicit 1.25 where declared).
- Ready-made pairs for `code --diff`: `re_work/compare/N_*_generated.con` vs `N_*_reference.con`.

## Where the ORIGINAL spawn position is (and is not) in a demo - verified 2026-10-13

- `ServerConnection::clientSendDatabase` (0x0808a020) builds the join snapshot with the object's
  *live* position (vtable+0x6c) and the rotation from its *current* matrix (`getRotationZXY`).
  `GameServer::createObjectOnAllClients` (0x080b0420, used for objects created during play) sends the
  requested spawn transform. So: a vehicle created DURING the recording carries its exact spawn
  transform in `CreateObjectEvent`; vehicles that existed when the recording began carry the position
  after physics settled them.
- Timeline of a fresh vehicle (tnk_type98, claude_spawn demo, tick 2951): creation event Y=184.096
  (exact spawner Y); next tick the first physics step pops it +0.92; then it sinks over ticks to its
  rest height (+0.67 over the spawner Y). A recording from map load starts after that is over
  (autoRecord first packet is tick ~30, coop tick 1).
- No raw float32 of the original Y exists anywhere in the demo bits (searched every bit offset of every
  packet for the spawner coordinates; only unrelated hits). Vehicle ghost updates resend the current
  raw position triple while it moves, then compressed vectors (SimpleObjectNetworkable: 19-bit mask,
  bit1 position via `readCompressedVector`, bit0 `readUnitQuaternion(14)`, delta against a baseline).
- Rest height over the spawner is constant per template for ground vehicles (e.g. jep_vodnik +1.135,
  aav_tunguska +0.963, boat_rib -0.191; MAD 0.000 over many spawners) when the spawner stands on
  terrain; aircraft/deck spawners vary. `--estimate-settle` (opt-in, table
  `assets/settle_offsets.json` from `scripts/build_settle_table.py`) subtracts it: within 1 cm for 21 of
  24 ground-vehicle spawners, wrong by ~1 m otherwise. The user rejects estimates: default is OFF,
  snapshot value written and flagged approximate.
- To get exact values for every spawner: record a stretch in which each vehicle respawns (any real round
  has many respawns; on the test server lift/destroy vehicles after round start).
- USER RULE: zxc.bf2demo and the bf2rangers demos were recorded mid-round - never use them for
  accuracy experiments or to train tables; use light demos recorded from map load (`auto_rot_*`,
  `auto_coop_dalian16`, the ones recorded on the test server). They remain valid only as protocol
  regression inputs.

## Bit coverage (scripts/bit_coverage.py)

Understood today: events 100%, ghost record headers 100%, ControlPoint ghost bodies. In zxc only
21.6% of all bits are decoded; vehicle (PlayerControlObject root) ghost bodies are 49% of the bits
(80% in claude_spawn), then Soldier 10%, GenericProjectile 9.5%, UAV 4.7%, SupplyObject 1.4%.
Vehicle ghost id == root object id (children are not separate ghosts). A ghost body is the
concatenation of per-networkable updates in descriptor order (no per-networkable length);
`NetworkManager::analyseObject` (0x0846ada0) builds the descriptors; classes with setNetUpdate:
Player, OverheadCamera, Engine, Kit, ControlPoint, Soldier, SimpleObject, Spring, DestroyableObject,
TriggerableTarget, FreeCamera, RotationalBundle, PlayerControlObject (11-bit length + wrapped
networkable, or 4-bit mask of weapon indices), Item, GenericProjectile, DestroyableWindowsBundle,
ScoreManager, TargetObject. Per-template NetworkableInfo comes from `setNetworkableInfo` in the
.con/.tweak files (BasicInfo 534x, SpringInfo 87x, KitInfo, HandFireArmsInfo, DestroyableObjectInfo...).

## Test server (<dedicated server folder>, Windows dedicated 1.5.3153)

- Start: `bf2_w32ded.exe +modPath mods/bf2 +config mods/bf2/settings/<cfg>.con +mapList mods/bf2/settings/<list>.con`
  (working dir = server dir). `ServerSettings_auto.con` + `maplist_auto.con` = autoRecord on,
  4-map rotation. `sv.autoRecord 1` starts recording at **map load** (first packet ~tick 30);
  the demo file is written on round end / `admin.runNextLevel` (size 0 until then).
- rcon: `python scripts/rcon.py "<cmd>"` (port 4711, password `re`). Works with the stock
  `default` admin module, no ModManager needed. `demo.recordDemo <name>` fails silently
  (only a message in the server console) if the file already exists.
- Embedded Python is 2.3: no `os.path`, no `traceback.format_exc`, only the `default`
  adminScript is loaded; the object wrapper has no `setDamage` (lift with `setPosition`).
  Lifting static structures crashes the server.
- Custom map test: replace `Levels/<Map>/server.zip` with an edited copy (original kept as
  `server.zip.bak`), run, export, `compare_con.py` against the edited .con, then restore.
  See `re_work/make_custom_zip.py`.

## Tooling in this repo

- `python scripts/decomp.py OUT.c 0xADDR|name ...` — decompile from the
  persistent Ghidra project `re_work/ghidra` (gitignored; join selectors with
  spaces, the script uses `+` because cmd.exe splits on commas).
- `re_work/ia32.asm` — full `objdump -d -C` of `bf2_ia32` for xref greps.
- `re_work/server/root/mods/bf2` — files from the official Linux server
  installer (the exact content the recording server ran).
- `python scripts/build_templates.py <mods/bf2>` — rebuild templates.json.
- `python -m unittest discover -s tests -t .` — regression tests.

## Rules

- Evidence over plausibility: never invent a field name or width that is not
  backed by a decompiled read or by consistent decoding across samples.
- The runtime parser must work without the game installed; game-derived data
  is extracted once into `bf2demo/assets/` (`scripts/extract_assets.py`), and
  optional live correlation (`bf2demo/level_anchors.py`) degrades gracefully.
- Do not commit large binaries or Ghidra project files.
- Code, comments and commit messages in English.

## Kill feed, game log, players, scoreboard (`bf2demo/feed.py`)

CLI: `--feed`, `--feed-verbose`, `--scoreboard`. Assets: `hud_strings.json` (game HUD message templates, built by
`scripts/build_hud_text.py`), `hud_names.json` (weapon/vehicle `hudName` -> English, `scripts/build_templates.py`),
`team_names.json` (`gameLogic.setTeamName` per level). Localization lines are `KEY<pad?><ESC><ESC>text<ESC><ESC>`:
the padding may be absent (long keys), so the key regex must be `^(\S+?)\s*ESC ESC`.

* `KilledBy` byte order: FIRST u8 = killer (`attacker_id`), SECOND = victim (`victim_id`). Proven by the two OCR
  TeamKill lines and by Player-ghost score counters. Wording: weapon hud name, else vehicle hud name; weapon template
  0 and no name -> `HUD_HUD_KILLEDBY_KILLED` ("[Killed]"); weapon with empty hud name -> "[]"; killer==victim ->
  "X is no more."; same team -> `[TeamKills - ...]`. zxc vs OCR: 74/76 lines identical (the other 2 are an OCR typo
  ZTZ-99 and blank spacing); the demo has 4 more kill events than the OCR transcript.
* `CreatePlayer` fields: team (3 bits, equals Player ghost team), field_d(4), is_remote, player_id, ghost_id
  (id of the Player ghost), unk_34, is_ai, name (names carry a leading space when there is no clan tag).
  `DestroyPlayer` -> `GAME_MESSAGE_PLAYER_DISCONNECTED` ("X has been disconnected from server").
* Squad events `JoinSquad/LeaveSquad/SetSquadLeader` read (team, player, squad); `ChangeSquadName` reads
  (team, squad, player) (verified against Player ghost squad ids).
* Player ghost = `Player::setNetUpdate` 0x080f11c0, `networkables.decode_player` consumes every record exactly
  (8511/8511 on zxc). 28-bit mask; fields: alive, spawn group, PlayerScoreData (score +0x00 signed 11, +0x10, +0x14
  kills(?), +0x04 signed, +0x18), flag holder, medic call, firing slots, sprint, 11-bit +0xdc, 32-bit time + flag
  (= server tick + 30, NOT an address), team(3 bits -1), camera, kit, squad id, rank block, free/overhead camera,
  commander block. Counter semantics: +0x14 increments with the first KilledBy byte (kills) at lag 0; +0x10
  increments with the second byte (deaths) but also ~every 30 ticks for other reasons (not yet understood), so the
  scoreboard counts kills/deaths from events and shows +0x00 as Score.
* IP / network identity: NOT in the demo. No dotted-quad text anywhere in zxc/rangers (any bit alignment), the only
  per-player identity in CreatePlayer/ChangePlayerName/Player ghost is name + player_id. State this honestly.
* Not yet decoded: chat (PostRemote kinds 0/2/6 payloads), Vote/Commander/Medal field meaning (rendered raw).

### Kill feed visibility flag and capture credit (2026-10-13)
* `KilledByEvent` byte +0xe (`flag_e`): False => the game's kill feed does NOT show the line. Evidence: every False event
  in zxc (3) and bf2rangers001 (2 in the screenshot window, 1911/5462/6669) is absent from the in-game feed/OCR; every True one
  is shown. `executeClient` (0x08075ee0) itself ignores it (it raises GameEvent 0/3 for the HUD and applies the death effect
  to the player in byte +0xd = victim), so the filter lives in the BF2.exe HUD listener, which was not decompiled yet.
  `build_feed` hides them unless `verbose` (then marked "not shown in the game HUD").
* Capture credit: the server raises `PlayerScoreData.score` (Player ghost mask 0x8, field score_0) in the same packet as
  the ControlPoint team change: +2 for the capturer/neutralizer, +1 for helpers. `Player.score_history` + `_participants()`.
  Neutralization = CP team -> 0 (feed kind `neutralize`).

### BF2.exe (client) analysis - kill feed, assists (2026-10-13)
Ghidra program `BF2.exe` (stripped Windows client, same file as the installed one) is in `re_work/ghidra` project `bf2`.
`python scripts/decomp.py --program BF2.exe --script FindStringRefs.java OUT.txt NEEDLE+NEEDLE` lists code that references a
string; `python scripts/decomp.py --program BF2.exe OUT.c 0xADDR` decompiles. HUD game-event handler = `FUN_00753de0`
(BF2HudManager.cpp), `switch(eventId)` on category 0 events: 3/0xe = KilledBy (kill feed), 9 = kill assist, 10 = replenish,
8 = team change, 4 = tickets low, 1 = pause.
* `KilledBy.has_killer` (byte +0xe): `world::fillKilledByData` (server 0x080dfe70) sets it to 1 only when a killer Player exists;
  otherwise the killer id stays 0. So with has_killer False `attacker_id` (always 0) is NOT a player (57/57 in the samples) and the
  HUD prints nothing (needs killer object, or killer id 0xFD/0xFE special cases which need a killer anyway). weapon_template_id
  = template of the damaging object (+0x18), vehicle_template_id = template of the root parent of the weapon (+0x14).
* Kill assists: `GameLogicDamage::serverGiveDamage` (0x080dfff0) broadcasts KilledBy, then for every (assister, type) in its
  assist map sends `PostRemoteEvent(category 0, id 9, data=type)` UNICAST to that assister only (`game->vtable+0x98`), and the HUD
  turns it into `HUD_HUD_ASSIST_KILL_*`. Unicast events are not in a demo: no category-0 id 9/10 PostRemote exists in any sample.
  Likewise replenish (id 10: heal/repair/ammo/driver/revive) and `sgl_sendGameLogicEvent` events. Assists are therefore only
  derivable from the score (+1 per assist at the kill tick, `scoringCommon.py`: kill +2, teamkill -4, suicide -2,
  damage/targeter/driver assist +1, passenger 0).
* PostRemote categories: 0 = game logic (python `sgl_sendGameLogicEvent`, ids <= 0x18), 2 = HUD (`sgl_sendHudEvent`, ids < 0x4f; also
  engine events with 24-byte payloads: setTeam, resurrect id 0x33, handleHudEvent), 6 = python events broadcast (6,10 =
  GameLogic::killPlayer: player id + the same has_killer-like flag, 6,9 = spawn?). PostRemote layout: kind(4), id(32), delay float(32), len(8), data.

### PostRemote = EventManager events (2026-10-13, from BF2.exe registerEvent tables)
`bf2demo/postremote.py` + `assets/event_names.json` (`scripts/build_event_names.py`; client registers events as
`registerEvent(category, id, name)` in FUN_00442d90 / FUN_004f6690 / FUN_0074e090). Categories: 0 GameLogic, 1 Game, 2 Hud, 6 Network.
* (2,0x2b UnitSpotted, 0x2e CallForMedic, 0x2f CallForAmmo, 0x30 CallForRepair, 0x31 CallForRevive, 0x32 AutoCallForRevive): 24-byte
  `SpottedEvent` forwards `<hhIffII>` = object_a (caller/spotter soldier object), object_b (spotted object, 0 for calls), team (byte),
  x, z, 0x1a, id. AutoCallForRevive is sent when a soldier dies. Soldier object -> player is NOT in the stream (a nearest-kill match
  gave conflicting owners, so it is not used).
* (6,9) PlayerSpawned(player id), (6,10) PlayerDead(player id, 1 = no killer player), (0,19)/(0,20) UAV created/destroyed
  (object id, team), (0,21..23) drop vehicle objects, (0,1) GameStatus, (2,0x21) CommanderAccept(player id, 1.0), (2,0x25) Resign.
* Player ghost `killed_by` (mask 0x1000000, Player+0x314) = id of the killing player, -1 after respawn (123/123 matches with KilledBy).

### Vote, Medal, Commander, round events (2026-10-13)
* `VoteEvent` (0x08081c00; read order +0x20(discarded), +0xc, +0x10, +0x20, +0x11, +0x12, +0x21, +0x14, +0x18, +0x1c): option (0 yes / 1 no),
  yes_votes, item (player id for kick/commander, map-rotation index for map votes, 0xff none), no_votes, votes_needed, caster (= last
  ballot's player, 0xff none), status (0 state, 4 commander state, 7 not enough players, 8/9 client requests), vote_type (1 map, 2 kick,
  3 commander/mutiny), time_remaining float. The server repeats the state for every client request, so the feed de-duplicates.
  Wording = `HUD_HUD_KICKVOTE_{PLAYER,MAP,COMMANDER}_STAT` + `HUD_LEVELNAME_<level>`.
* `MedalEvent`: name key `AWARD_Name_<award_id>_<level>` (ribbons without `_level`), from BF2.exe FUN_007bbb60. Medal/Rank events are broadcast
  (`sgl_sendMedalEvent` uses game vtable +0x84), unlike assists/replenish which are unicast (+0x98).
* `CommanderEvent` action 3 = commander change: fields (team byte, player short, -1 = none). Verified: a successful mutiny vote is followed by
  "team has no commander". Other actions are client requests.
* `BeginRoundEvent.state` = bf2.GameStatus (1 Playing, 2 EndGame, 3 PreGame ...); `EndOfRoundEvent`: winner, team1_value, team2_value (never seen in a sample).
* `scripts/decomp.py --timeout SECONDS` for very large functions.
* Soldier object -> player: `EnterVehicleEvent(player, soldier object, flag=True)` arrives in the tick the Soldier is created, together with
  `PostRemote(6,9) PlayerSpawned(player)`; 155/155 (rangers001), 114/114, 116/116 match. `GameObject.owner_id` / `enters`. Object ids are
  reused after DestroyObject, so ownership is per instance (id + created_tick). Spot/call events resolve their soldier object to a player.
* PlayerScoreData in the Player ghost (names from `pmgr_getScore/setScore`): psd+0 score, +4 skillScore, +0x10 deaths, +0x14 kills, +0x18 TKs,
  (+8 rplScore and +0xc cmdScore are not networked here). Deaths grow exactly with `PostRemote(6,10) PlayerDead` (one per death, also without
  a killer); kills match KilledBy except kills the python scoring ignores. `build_scoreboard` prints these absolute counters.

### Ghost bodies (2026-10-13): what is decoded bit-exactly
Method: write the networkable reader from the decompile, run it over every ghost update of a class and demand `remaining bits == 0`
(`scripts/ghost_probe.py`). `bf2demo/ghostbits.py` (readCompressedVector / 2 / readUnitQuaternion, width_for), `bf2demo/objectnet.py`.
* **Soldier** root body = `SoldierNetworkable` alone (0x08249860): 21-bit mask, state fields, weapon slot field is 4 bits, ragdoll records
  (mask 0x8000) = 9 bits + 3 raw float32 (bone 0 = world position of the body) + 3 x readCompressedVector2. 233061/233061 (rangers001) and the
  same on rangers002/003/zxc. Positions are ABSOLUTE float32 triples (compression mode 0) in every soldier/vehicle sample.
* **SimpleObjectNetworkable** (0x08243990, 19-bit mask; no-baseline path): pos (readCompressedVector, scale 0.0005), physics: vel (scale 0.001)
  and angular velocity (readCompressedVector2), quaternion = 4 x 14 bits, more vectors/flags by mask, health field (mask 0x10) of
  `width_for(armor.maxHitPoints + armor.wreckHitPoints)` bits (value - wreck = hit points; templates.json now stores both), PlayerControlObject
  weapon-slot fields. SupplyObject and UAVVehicle bodies are exactly this networkable (0 bits left on 100% of records).
* Vehicles (PlayerControlObject roots) = SimpleObject + further networkables (PCO 4-bit weapon mask, Engine 11-bit mask, Spring, RotationalBundle,
  DestroyableObject ...) whose list depends on the template; not decoded yet. Their pose (first networkable) is read by `decode_simple_object_pose`.
* `bf2demo/tracks.py`: `build_tracks(replay)` -> Track per object instance with (tick, position, rotation); `--tracks`, `--export-tracks OUT.csv`.
  First sample vs CreateObject position: median 0.008 m (rangers001).

### External sources reviewed (2026-10-13)
* **OpenBattlefield2** (https://github.com/Moxnatiy/OpenBattlefield2, MIT, docs/functions/network-events.md, player-state.md, score-manager.md,
  game-events.md, formats/network-protocol.md): an independent reverse engineering of the same 1.5.3153 Linux server + BF2.exe. It AGREES bit for bit
  with ours on: 7-bit event ids and the three streams, ghost record layout, template ids as a creation counter, SimpleObject / Soldier / Player layouts
  (incl. widths: ranged read = smallest n with 2^n-1 >= range+1), ragdoll = 9 bits + particle 0 raw + three wide vectors, PostRemote categories
  (6 network, 2 HUD), "tag + space + name". New facts taken from it: ghost time is in 1/30 s ticks; the ghost record length width is a GhostManager
  field (11 on their live server, 13 in our demos); ragdoll particles are bones 6, 1, 15, 31 (`ragdoll_net_boneEnable` 15), the wide vectors
  are relative to particle 0 with precision 0.01; soldier mask 0x2 yaw (+-360), 0x4 pitch (+-90), 0x8 (+-180), 0x10 (+-90) as 12-bit values,
  0x400/0x800 10-bit +-50, 0x1000 = itemIndex of the weapon in hand (width = soldierTemplate.inventorySize 10 + 1 range -> 4 bits);
  Player ghost: 0x100 = ping, 0x20 = spawn tick + man-down flag, 0x4000 first/second/third places, psd+4 = teamwork (rplScore);
  ScoreManager ghost = 32-bit mask + 18-bit numbers, bits 0x400 / 0x400000 = tickets team 1 / 2 (18 bits + flag + 18-bit ticket state).
  In a live network stream compressed vectors are relative to the object's previous/compression-vector position; in our demos every
  position is raw (mode 0).
* **Refractor-2-BitStream-Emulator** (https://github.com/matthias-hoste/Refractor-2-BitStream-Emulator): C# read/write bit operations; no packet docs.

### Vehicle networkable sequences, helicopters/boats/jets (2026-10-13, milestone 2)
`scripts/netseq.py` + `objectnet.decode_vehicle` now explain every vehicle class seen in rangers001/002 at 99.8-100% (bit coverage
rangers001: 98.1%). Rules proven by exact consumption:
* `Rotor` is NOT a rotational bundle: its ghost carries one `SimpleObjectNetworkable` (letter O, 19-bit mask, mobile=True) per rotor template
  (`ahe_ah1z` = `OORREE`: mainrotor, tailrotor, rotorhead, rotorhead2, rotor engine, tail engine; mi17/z10/uh60/z8 confirm).
* `compareProperties` (0x0846ab10) merges objects only when the class ids are equal (or RotationalBundle<->Camera) AND the class is a
  RotationalBundleTemplate: Wing and Engine take part, Rotor does not. Compared: min/max rotation, max speed, acceleration,
  setInputToYaw/Pitch/Roll and the flag at template +0x1e8 which is `setAutomaticReset` (NOT snapToZeroOnNoInput; makeScript 0x081ecf20).
  Examples: F-18 twin engines merge (`RRRRER`), boat_rib rear wing differs from the vertical wing in setAutomaticReset (`RRRRERRR`).
* EngineNetworkable flags are bits of `EngineTemplate::getEngineType()` (value of `setEngineType`, enum from `operator<<` 0x082a3c10:
  Plane 1, Car 2, Tank 6, Ship 9, Rocket 0x11, Torpedo 0x19, Helicopter 0x21, NewCar 0x42, NewTank 0x46, NewCar2 0xc2): bit 0x20 enables the
  mask-0x100 field (helicopters), bit 0x80 the 0x400 block. The flag is per engine element (F-35B mixes Plane and Helicopter engines).
* RotationalBundleNetworkable field width is `0xc + 4 * (precision == StatePrecisionFull)`; the ghost records here always use 12 bits except
  possibly the first full-state record of an object (about 0.1% of vehicle records, not explained yet: tried 16, worse).
* NetworkableInfo flags (Common/Networkables.con): `setIsUnique` (SpringInfo) = never merge, `setForceNetworkableId` (HandFireArmsInfo) = non-root objects
  with that info are not part of the root ghost.
* Parachute (class `Parachute`, a PlayerControlObject root) = SimpleObject + its derived wings (`RRRRRR`); 97.6% exact on zxc (misses = first full-state records).
* Nested PlayerControlObjects (turrets/gunner seats): the first one has its own ghost with id `root id + 1` (passenger seats never appear). Body =
  `decode_pco_slots` (PlayerControlObjectNetworkable 4-bit mask) + the child's own derived sequence (`PRR`, `PRRR` ...). Stored per root as
  `TemplateInfo.pco_children` (templates.json entry index 7, preorder = `getAllPlayerControlObjects`); `objectnet.decode_child_pco`. 100% on
  rangers001 for jeep_faav, z10, ah1z, m1a2, z8, boat_rib, paratrooper.
* `scripts/bit_coverage.py` now also counts packet framing and padding; bits understood: rangers001 99.8%, zxc 99.5%, auto_coop 99.8%. Left:
  Player-less unknown ids (0.1%), OverheadCamera root (0.1%), the first full-state record of some objects.
* Exactness fixes of the full-state (first) records, all proven by exact consumption on rangers001/002/003, zxc:
  `EngineTemplate::numberOfGears` defaults to 1 (ctor 0x082a3ce0, so the gear field is 2 bits when the template does not set it; -1 = no field);
  the Rotor element is a SimpleObject with `is_player_control=True`, `mobile` from its own template and range from its own armor;
  `ArmorTemplate` defaults maxHitPoints = wreckHitPoints = 10 (makeScript 0x0821f840 prints a value only when it differs from 10.0), so a
  template with an Armor component but one value unset counts the other as 10 (trestle01_dest, sign_author_perso); a Parachute root uses the
  parachute field (`is_parachute`) instead of the weapon slots.
* ScoreManager (0x0810a5d0): every mask bit carries signed numbers (sign bit + 17 bits): one by default, two for bits 4/16/24/25, ticket bits 10/22 =
  number + flag + number, bit 30 a signed 2-bit number, bit 31 = signed 2-bit + two signed 17-bit numbers (full state = 724 bits).
* SpawnGroup ghosts (id = `CreateSpawnGroupEvent.object_id`, 6-bit mask: 0x1 minimap x/z bytes, 0x2 team(4), 0x4 active, 0x8 flag, 0x10 flag, 0x20 squad(8)-1)
  and OverheadCamera (4-bit mask) decode exactly (`networkables.decode_spawn_group`, `objectnet.decode_overhead_camera`).
* Physical units (`objectnet.rotational_bundle_units`, `engine_units`, `tracks.build_tracks(parts=True)`, CLI `--export-parts OUT.csv`): rotation angle =
  normalised value * 180 degrees; angular velocity = normalised value * |template maxSpeed axis| * 16; engine rpm = normalised value * 1.25 *
  max(|min|,|max| rotation limit). `TemplateInfo.engines` holds one info dict per letter of `netseq` (aligned).
* Bits understood (scripts/bit_coverage.py, framing included): 99.3-100% on every sample. Left: ~10 passenger-seat ghosts of 301 bits (jep_vodnik, the_mi17 seats
  after the first nested PCO) and nothing else.
* JSON export (`bf2demo/jsonexport.py`, CLI `--export-json OUT.json [--json-tracks] [--json-parts] [--json-indent N]`): document `bf2demo-json/1` with
  demo header, players (histories), feed (verbose, with structured `data`), scoreboard, tickets, control points, objects and optionally tracks
  (`[tick, x, y, z, qx, qy, qz, qw]`) and vehicle element states. zxc with parts = 23 MB, 17 s.
* Passenger seats (nested PCO without a Camera in its subtree): `IPlayerControlObject::getOwnCameras()` empty -> body = 11-bit length + a wrapped
  SoldierNetworkable (the occupant); with cameras: 4-bit weapon block + own sequence (`TemplateInfo.pco_children` entries are `[seq, elements, has_camera]`).
* Event field names resolved from the binary: CreateSpawnGroup (active, only_for_ai, has_spawn_points, map_x/map_z), SetAcceptOrder (accepted, order_type,
  squad_order_type), IssueSquadOrder.kind (0 squad order, 1 commander order, 2 request), StickyProjectile (net_id_count, child_index, player_id, 4-row matrix),
  AmbientEffectArea (effect_index, object_id), CreateKit (kit_id = Kit::getCreationIndex, kit_state = Kit +0x174).
* Validation demo with EVERY vehicle: `scripts/make_vehicle_test_zip.py` writes a Dalian server.zip with one ObjectSpawner per PlayerControlObject root
  template (run-time `object.create` asserts "no collision mesh"; the template `bipod` crashes the loader and is skipped; the server dies silently during load
  when a template is bad - bisect the template list). `samples/auto_all_vehicles_dalian16.bf2demo`: 50 templates, 100% exact, including templates that no
  round sample contains (btr90, lav25, su30, mig29, su34, tunguska, type95, m6, havoc, technical, truck1, f15, radars). Do not launch the server with output
  redirection (the console cannot be sized -> assertion). Restore `server.zip` from `server.zip.bak` afterwards.
* Special Forces (`mods/xpack`, levels surge, ghost_town, iron_gator, leviathan, mass_destruction, night_flight, warlord, devils_perch): the xpack mod mounts its own
  `Objects_server.zip` BEFORE the base mod's, so its global template block differs (6626 templates). `build_templates.py BF2_ROOT OUT.json XPACK_ROOT` stores it under
  `xpack` in templates.json and `TemplateDB` selects it by level name (ids verified on recorded Surge/Ghost Town demos: no unknown template, CP block aligned).
  New ghost classes there: `Triggerable` (= SimpleObject body) and `TriggerableTarget` (`decode_triggerable_target`: 4-bit mask, position, rotation, two values; the elevators).
* BUG FOUND with the booster demo (`auto_all_vehicles_booster_midnight_sun16`): the booster pack archive is merged into the sorted .con order, so its templates are
  INTERLEAVED with the base ones (ids shift from about 54 on). `booster_global` in the asset is now the full table (not an appended tail). The asset is `templates.json.gz`.
  `FloatingBundle` is a rotational-bundle-like element (R), merged like wings; booster vehicles (a10, su39, wz11, ec635, littlebird, musclecar, fantan, semi) are exact.
* Static objects (`bf2demo/export_static.py`, CLI `--export-static OUT.con`): the destructible statics (bridge segments, crates, barrels, signs, fuel wagons ...) are
  `DestroyableObject` / `SimpleObject` CreateObject events in the join snapshot and carry the exact StaticObjects.con transform. Verified against the retail files of
  8 of 9 maps recorded from map load (identical multiset of (template, position 3 decimals, rotation 1 decimal; 180 == -180); the 9th differs by one `barrel_blue`
  that has physics and had settled). Not in a demo: layer (written 1), light mask, overgrowth, object order. Server-side custom maps are essentially edits of
  StaticObjects.con + GamePlayObjects.con, so these two exporters recover them.
* Spawn coordinates before physics: an object CREATED after recording starts has its spawner transform exactly (test map: spawners at Y=170.000 -> events carry 170.000);
  mobile objects already in the join snapshot are settled. Spawner initial delays make a recording from map load see most spawns as fresh creations.
* Dev tools: `scripts/make_vehicle_test_zip.py`, `re_work/record_all_maps.py` (not committed: loops the test server over a maplist ending each round after N seconds).
* `sv.demoQuality` q (1..10, ServerSettings +0xbc; ClientConnection ctor 0x080826f0, demo mode): t = (q-1)/9; max packet bytes (`ClientConnection+0x18`, `newPacket`) =
  `int(t*3836)+260`; connection field +0x14 = `int(t*16)+4`; `GhostManager(mode 1, floor(t*215)+40)` (max ghost records per packet; other modes use 40).
  Measured on 4 recordings of the same map: q1 max 260 B / avg 212 B, q2 686 / 327, q3 1111 / 354, q10 3567 / 361. Precision of the fields does not change: every decoder is
  exact at every quality (samples `auto_all_vehicles_dalian16_quality{2,3,10}`); higher quality only fits more state updates per tick (finer position/rotation sampling).
* DEDICATED SERVER LOAD HANG (found 2026-10-14 on a customised Taraba Quarry): the server stopped at "Loaded 14%" with no error when `GamePlayObjects.con` contained a
  very long line (the exporter's notes block had `rem` lines up to 2205 characters). The longest line in any retail file is 93 characters; the exporter now wraps every note
  to 100 (`export_con.MAX_LINE`). Sections alone or in pairs loaded; only the long-line notes block hung (bisected with hybrid files). Also fixed: a spawner seen only with
  team 0 at a neutral control point was written WITHOUT `setObjectTemplate` (and could not match its layout spawner); it now matches by template and, when new, writes its
  vehicle to both team slots (`DemoSpawner.template_slots`). A server whose map-load state cannot be read over rcon (rcon answers while loading) is checked by reading the
  console text (`re_work/console_text.py`: AttachConsole + ReadConsoleOutputCharacter; "Loaded 100%" = loaded).
* CLIENT DESYNC FROM NEW TEMPLATES (found 2026-10-14): a server-side custom map that adds `ObjectTemplate.create` lines makes a client that has the original map files
  fail with "Networkable already added to network manager, netId=0": template ids are a creation counter and the client numbers its own templates, so one extra template
  shifts every later id. The exporter therefore keeps the layout's template list (`allow_new_templates=False`): extra objects are further INSTANCES of an existing template.
* Spawn groups (validated 106/106 on 22 maps): group = `(setControlPointId, setGroup)` of SpawnPoint templates; position = mean of its points' `absolutePosition`
  (`SpawnGroup::calcNewPos` 0x08111540); wire = two bytes `int((size/2 + coord)/size*255)` with `size` = `heightmapcluster.setHeightmapSize` of the level's Heightdata.con
  (2048, or 1024 for Blue Pearl, Karkand and every Special Forces map; `assets/world_sizes.json`, `scripts/build_world_sizes.py`). `bf2demo/spawngroups.py`.
  So a demo recorded with nobody spawning still tells where each control point's spawn points are centred (+-half a cell, 8 m / 4 m) and whether a layout's points belong to the map.
* Static spawners: "not in the demo" is NOT "not in the map" (a spawner without a vehicle for the control point's owner is idle). Dropped only when provable: static vehicle for the
  owner's slot, snapshot at map load (first tick <= 900): 0 false drops over 515 observed + 113 unobserved spawners of the 22 retail maps (`re_work/absent_rule.py` logic, tests).
* Notes in the exported file must be short lines (see the 14% hang above).
