"""Protocol, template resolution, replay model, kill feed and scoreboard (full-round samples are protocol regressions only).

Run everything with ``python -m unittest discover -s tests -t .``.
"""

from __future__ import annotations

import difflib
import math
import os
import re
import struct
import unittest

from bf2demo.feed import build_feed, build_scoreboard
from bf2demo.packet import parse_packet
from bf2demo.postremote import decode_post_remote

from .common import SAMPLES, all_samples, demo, replay


class PacketLayoutTest(unittest.TestCase):
    def test_every_packet_is_consumed_to_within_its_padding(self):
        for name in ("test1.bf2demo", "cp_test1.bf2demo", "test_dalian32.bf2demo", "test_kubra16.bf2demo", "customTara.bf2demo"):
            for packet in demo(name).packets:
                if packet.data:
                    parsed = parse_packet(packet.data)
                    slack = parsed.total_bits - parsed.end_bit
                    self.assertTrue(0 <= slack < 8, f"{name} packet {packet.index}: slack {slack}")


class DemoQualityTest(unittest.TestCase):
    """``sv.demoQuality`` q (1..10) sizes the recording connection (ClientConnection ctor, demo mode): with t = (q - 1) / 9 the
    maximum packet is ``int(t * 3836) + 260`` bytes and a packet holds at most ``floor(t * 215) + 40`` ghost records. Quality
    changes how much state fits per tick, never the field precision: the same decoders are exact at every quality."""

    def test_packet_size_limit_follows_the_quality(self):
        for quality, name in ((1, "auto_all_vehicles_dalian16.bf2demo"), (2, "auto_all_vehicles_dalian16_quality2.bf2demo"),
                              (3, "auto_all_vehicles_dalian16_quality3.bf2demo"), (10, "auto_all_vehicles_dalian16_quality10.bf2demo")):
            limit = int((quality - 1) / 9 * 3836) + 0x104
            sizes = [len(p.data) for p in demo(name).packets if p.data]
            self.assertLessEqual(max(sizes), limit, name)
            if quality < 10:
                self.assertGreater(max(sizes), limit - 80, name)     # the limit is actually reached
            records = max(len(parse_packet(p.data).ghosts) for p in demo(name).packets if p.data)
            self.assertLessEqual(records, int(math.floor((quality - 1) / 9 * 215)) + 40, name)


class TemplateResolutionTest(unittest.TestCase):
    def test_every_object_of_every_sample_resolves_to_a_template(self):
        """Includes all 22 base maps, the booster pack and Special Forces (their own template tables)."""
        for name in all_samples():
            rep = replay(name)
            unknown = [o.template_id for o in rep.object_history if o.template.source == "unknown"]
            self.assertEqual(unknown, [], name)
            if rep.control_points:
                self.assertTrue(rep.templates.aligned, name)

    def test_special_forces_levels_use_their_own_table(self):
        for name in ("auto_xpack_surge16.bf2demo", "auto_xpack_ghost_town16.bf2demo"):
            self.assertGreater(replay(name).templates.global_count, 6000, name)

    def test_booster_pack_levels_use_the_merged_table(self):
        self.assertEqual(replay("map_midnight_sun.bf2demo").templates.global_count, 6196)


class ReplayTest(unittest.TestCase):
    def test_dalian32_control_points_and_vehicles(self):
        rep = replay("test_dalian32.bf2demo")
        cps = {cp.template.name: cp for cp in rep.control_points.values()}
        self.assertEqual(len(cps), 6)
        self.assertEqual(cps["CPNAME_DP_32_uscarrier"].team, 2)
        self.assertEqual(cps["CPNAME_DP_32_airfield"].team, 1)
        names_at = {tuple(round(c, 1) for c in o.position): o.template.name for o in rep.object_history if o.position}
        self.assertEqual(names_at[(765.7, 141.2, -34.7)], "boat_rib")
        self.assertEqual(names_at[(766.5, 164.0, -27.4)], "air_f35b")
        self.assertEqual(names_at[(-603.0, 184.8, -373.0)], "tnk_type98")

    def test_custom_taraba_control_points(self):
        teams = [cp.team for cp in replay("customTara.bf2demo").control_points.values()]
        self.assertEqual(len(teams), 7)
        self.assertEqual(teams.count(0), 1)

    def test_respawned_vehicles_carry_exact_spawner_transform(self):
        """Recorded on a local server while lifting vehicles so they respawn; the expected values are the ObjectSpawner
        transforms in Dalian gpm_cq/32 GamePlayObjects.con (reference data, copied here)."""
        exact = set()
        for site in replay("claude_spawn_115014.bf2demo").spawn_sites:
            if site.exact and site.templates:
                for name in site.templates:
                    exact.add((name,) + tuple(round(c, 3) for c in site.position) + (round(site.rotation[0], 3),))
        for row in [("tnk_type98", -603.000, 184.096, -373.000, 37.105), ("ahe_ah1z", 786.562, 162.074, 5.037, -50.000),
                    ("air_f35b", 752.827, 162.074, 23.707, -89.259), ("boat_rib", 765.651, 141.400, -34.735, -178.139),
                    ("chthe_z8", -639.000, 184.096, -316.000, 80.565)]:
            self.assertIn(row, exact, row)

    def test_objects_created_during_the_recording_keep_the_spawner_coordinates(self):
        """The test map puts every spawner at Y = 170.000: vehicles created after the recording started (before physics
        moved them) arrive with exactly that height."""
        rep = replay("auto_all_vehicles_dalian16.bf2demo")
        fresh = [o for o in rep.object_history if o.template.cls == "PlayerControlObject" and not o.snapshot and o.position]
        self.assertGreaterEqual(len(fresh), 10)
        self.assertTrue(all(o.position[1] == 170.0 for o in fresh))

    def test_map_size_comes_from_rotation_block(self):
        rep = replay("auto_rot_12_11_01.bf2demo")
        self.assertEqual((rep.level, rep.game_mode, rep.map_size), ("kubra_dam", "gpm_cq", 16))

    def test_every_base_map_demo_names_its_level(self):
        levels = {replay(n).level for n in all_samples() if n.startswith("map_")}
        self.assertGreaterEqual(len(levels), 22)


class PlayerAndFeedTest(unittest.TestCase):
    """zxc starts mid-round: protocol regression only."""

    @classmethod
    def setUpClass(cls):
        cls.replay = replay("zxc.bf2demo")

    def test_players_and_teams(self):
        by_name = {p.name.strip(): p for p in self.replay.player_history}
        self.assertEqual(set(by_name), {"Goku pc16", "asd pc15", "2026 pc03", "pc02", "wajiho pc01"})
        self.assertEqual({n: p.team for n, p in by_name.items()},
                         {"Goku pc16": 2, "asd pc15": 2, "2026 pc03": 1, "pc02": 1, "wajiho pc01": 1})
        for p in by_name.values():
            self.assertEqual(p.team, p.create_team)       # CreatePlayer team == Player ghost team

    def test_kill_feed_matches_in_game_ocr(self):
        norm = lambda text: re.sub(r"\s+", "", text)  # noqa: E731
        ours = [norm(l.text) for l in build_feed(self.replay) if l.kind in ("kill", "teamkill", "suicide")]
        path = os.path.join(SAMPLES, "zxc.target.ocr.from.game.correct.result.txt")
        if not os.path.isfile(path):
            self.skipTest("OCR reference not present")
        with open(path, encoding="utf-8") as fh:
            ocr = [norm(l) for l in fh if l.strip()]
        matched = sum(b.size for b in difflib.SequenceMatcher(None, ocr, ours, autojunk=False).get_matching_blocks())
        # 75 of 76 OCR lines (events with the KilledBy visibility flag False are not shown by the game); the other is an OCR typo.
        self.assertGreaterEqual(matched, 75)
        self.assertEqual(ours[0], norm("Goku pc16 [WZ-10] 2026 pc03"))

    def test_teamkill_wording_and_disconnect(self):
        lines = build_feed(self.replay)
        self.assertIn("pc02 [TeamKills - WZ-551 'Type-92A'] 2026 pc03", [l.text.replace("  ", " ") for l in lines])
        self.assertIn("Diehard has been disconnected from server",
                      [l.text for l in build_feed(replay("bf2rangers002.bf2demo"))])

    def test_scoreboard_rows(self):
        rows = {r.player.name.strip(): r for r in build_scoreboard(self.replay)}
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows["Goku pc16"].kills, 23)      # game counter (absolute; the recording starts mid-round)
        self.assertEqual(rows["Goku pc16"].score, 59)


class RoundEventsTest(unittest.TestCase):
    """bf2rangers001 is a full round (protocol regression)."""

    def test_capture_participants_from_score(self):
        rep = replay("bf2rangers001.bf2demo")
        cap = [l for l in build_feed(rep) if l.kind == "capture" and l.tick == 4403][0]
        self.assertEqual(cap.data["players"], [("kamiloo275", 2)])
        hidden = [l for l in build_feed(rep, verbose=True) if "not shown in the game HUD" in l.text]
        self.assertTrue(any(l.tick == 6669 and "AHMAD died (no killer player)" in l.text for l in hidden))
        self.assertFalse(any(l.tick == 6669 for l in build_feed(rep)))

    def test_post_remote_events_named_from_bf2_exe(self):
        rep = replay("bf2rangers001.bf2demo")
        decoded = {}
        for _, e in rep.events:
            if e.name == "PostRemote":
                r = decode_post_remote(e)
                decoded.setdefault((r.category, r.event_id), r)      # first occurrence
        self.assertEqual(decoded[(2, 43)].name, "UnitSpotted")
        self.assertEqual(decoded[(6, 9)].name, "PlayerSpawned")
        self.assertEqual(decoded[(0, 19)].fields["team"], 2)
        texts = [l.text for l in build_feed(rep, verbose=True)]
        self.assertIn("me_ became commander (US)", texts)
        self.assertTrue(any("UAV launched" in t for t in texts))

    def test_soldier_owner_from_enter_vehicle(self):
        rep = replay("bf2rangers001.bf2demo")
        spawns = [(t, struct.unpack("<I", e["data"][:4])[0]) for t, e in rep.events
                  if e.name == "PostRemote" and e["kind"] == 6 and e["value"] == 9]
        soldiers = [o for o in rep.object_history if o.template.cls == "Soldier" and o.created_tick >= 0]
        self.assertGreater(len(soldiers), 100)
        for obj in soldiers:        # every soldier is entered by the player named in PlayerSpawned, in the same tick
            self.assertTrue(any(p == obj.owner_id and abs(t - obj.created_tick) <= 3 for t, p in spawns))

    def test_death_counters_match_player_dead_events(self):
        rep = replay("bf2rangers001.bf2demo")
        dead = {}
        for _, e in rep.events:
            if e.name == "PostRemote" and e["kind"] == 6 and e["value"] == 10:
                pid = struct.unpack("<I", e["data"][:4])[0]
                dead[pid] = dead.get(pid, 0) + 1
        checked = 0
        for p in rep.player_history:
            if p.join_tick < 0 and p.leave_tick is None and "deaths" in p.first_state:
                self.assertEqual(p.state["deaths"] - p.first_state["deaths"], dead.get(p.player_id, 0), p.name)
                checked += 1
        self.assertGreaterEqual(checked, 5)


if __name__ == "__main__":
    unittest.main()
