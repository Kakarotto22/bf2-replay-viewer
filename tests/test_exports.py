"""Exporters: GamePlayObjects.con, StaticObjects.con, JSON, tracks and vehicle part states."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import unittest

from bf2demo.export_con import ExportOptions, export_gameplay_objects
from bf2demo.export_static import export_static_objects, parse_static_blocks
from bf2demo.feed import build_feed, build_scoreboard
from bf2demo.jsonexport import build_document
from bf2demo import layouts
from bf2demo.layouts import layout_text
from bf2demo.tracks import build_tracks

from .common import ROOT, replay


def _compare_con():
    spec = importlib.util.spec_from_file_location("compare_con", os.path.join(ROOT, "scripts", "compare_con.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# the game's own level text is not shipped in a public checkout: these tests compare against it
needs_layouts = unittest.skipUnless(os.path.isfile(layouts._PATH), "retail layouts not bundled (use --layout FILE with your own install)")


class GamePlayObjectsExportTest(unittest.TestCase):
    @needs_layouts
    def test_round_trip_of_a_map_load_recording(self):
        parsed = _compare_con().parse(export_gameplay_objects(replay("auto_rot_12_10_07.bf2demo")))
        cps = {c["name"]: c for c in parsed["controlpoint"]}
        self.assertEqual(len(cps), 4)
        self.assertEqual(cps["CPNAME_DP_16_powerplant"]["pos"], (-92.278, 153.181, -260.845))
        self.assertEqual(cps["CPNAME_DP_16_powerplant"]["tpl"]["props"]["team"], "1")
        # A static emplacement keeps its exact creation transform and team slot.
        spawners = [s for s in parsed["objectspawner"] if s["pos"] == (-93.745, 155.204, -245.007)]
        self.assertEqual(len(spawners), 1)
        self.assertEqual(spawners[0]["rot"][0], -24.492)
        self.assertEqual(spawners[0]["tpl"]["slots"], {1: "ats_hj8", 2: "ats_tow"})   # slot 2 from the layout

    def test_layout_matches_retail_format(self):
        """Retail section order and indentation, notes only after the body; CRLF is added when the CLI writes the file."""
        text = export_gameplay_objects(replay("auto_rot_12_10_07.bf2demo"))
        lines = text.split("\n")
        self.assertEqual([l for l in lines if l.startswith("rem ********** ")],
                         ["rem ********** Object Spawner (bf2demo parser) **********",
                          "rem ********** Spawn Points (bf2demo parser) **********",
                          "rem ********** Control Points (bf2demo parser) **********",
                          "rem ********** bf2demo parser notes **********"])
        self.assertEqual(lines.count("if v_arg1 == host"), 2)
        self.assertEqual(lines.count("endIf"), 2)
        host = lines.index("if v_arg1 == host")
        self.assertEqual(lines[host + 1], "")
        self.assertTrue(lines[host + 2].startswith("   rem [ObjectSpawner: "))
        self.assertTrue(lines[host + 3].startswith("   Object.create "))
        self.assertNotIn("\r", text)

    @needs_layouts
    def test_the_template_list_stays_the_layouts(self):
        """A client with the original map files numbers the templates itself: one extra template desynchronises it."""
        creates = lambda text: re.findall(r"(?m)^ObjectTemplate\.create\s+\w+\s+(\S+)", text)  # noqa: E731
        for name, level, size in (("custom_dalian16_edited.bf2demo", "dalian_plant", 16), ("customTara.bf2demo", "taraba_quarry", 32)):
            self.assertEqual(creates(export_gameplay_objects(replay(name))), creates(layout_text(level, "gpm_cq", size)), name)

    def test_new_templates_only_without_a_layout_or_on_request(self):
        edited = replay("custom_dalian16_edited.bf2demo")
        without_layout = export_gameplay_objects(edited, ExportOptions(use_layout=False))
        self.assertIn("ObjectTemplate.create ObjectSpawner", without_layout)
        self.assertNotIn("no object template was added", without_layout)

    def test_spawners_missing_from_a_map_load_snapshot_are_dropped_only_when_provable(self):
        """On every unmodified retail map no spawner is dropped (0 false drops over 22 maps); in the customised Taraba the
        statics that are not in the demo are gone."""
        for name in ("map_dalian_plant.bf2demo", "map_kubra_dam.bf2demo", "map_wake_island_2007.bf2demo"):
            self.assertNotIn("spawners of the layout are missing", export_gameplay_objects(replay(name)), name)
        self.assertIn("spawners of the layout are missing", export_gameplay_objects(replay("customTara.bf2demo")))

    @needs_layouts
    def test_spawn_points_follow_the_spawn_group_centroids(self):
        """Retail points are kept on an unmodified map (centroids equal the demo's groups) and dropped on the custom one."""
        retail = layout_text("taraba_quarry", "gpm_cq", 16).count("rem [SpawnPoint: ")
        kept = export_gameplay_objects(replay("map_taraba_quarry.bf2demo")).count("rem [SpawnPoint: ")
        self.assertEqual(kept, retail)
        custom = export_gameplay_objects(replay("customTara.bf2demo"))
        self.assertEqual(custom.count("rem [SpawnPoint: "), 0)
        self.assertIn("spawn groups of the demo have no layout counterpart", custom)
        with_placeholders = export_gameplay_objects(replay("customTara.bf2demo"), ExportOptions(placeholder_spawns=True))
        self.assertGreaterEqual(with_placeholders.count("rem [SpawnPoint: "), 9)

    def test_no_line_is_long_enough_to_hang_the_dedicated_server(self):
        """A 2205 character ``rem`` line in the notes block made the server stop loading Taraba Quarry at 14%; the longest line in
        any retail file is 93 characters."""
        from bf2demo.export_con import MAX_LINE
        for name in ("customTara.bf2demo", "auto_rot_12_10_07.bf2demo", "zxc.bf2demo"):
            lines = export_gameplay_objects(replay(name)).splitlines()
            self.assertLessEqual(max(len(l) for l in lines), MAX_LINE, name)

    def test_spawners_never_lack_a_vehicle(self):
        """A spawner template without ``setObjectTemplate`` (vehicle team unobservable) must still name its vehicle."""
        parsed = _compare_con().parse(export_gameplay_objects(replay("customTara.bf2demo")))
        for spawner in parsed["objectspawner"]:
            self.assertTrue(spawner["tpl"]["slots"], spawner["name"])

    def test_aligned_to_reference_adopts_structure_not_values(self):
        ref_path = os.path.join(ROOT, "re_work", "ref_dalian_cq16.con")
        if not os.path.isfile(ref_path):
            self.skipTest("reference .con (extracted from the game's server.zip) not available")
        from bf2demo.conparse import parse
        with open(ref_path, encoding="latin1") as fh:
            ref_text = fh.read()
        parsed = parse(export_gameplay_objects(replay("auto_rot_12_10_07.bf2demo"), ExportOptions(layout=ref_text)))
        ref = parse(ref_text)
        names = [s["name"] for s in parsed["objectspawner"]]
        ref_names = [s["name"] for s in ref["objectspawner"]]
        self.assertTrue(set(names) <= set(ref_names))
        self.assertEqual(names, [n for n in ref_names if n in names])       # same order as the reference
        cp = {c["name"]: c for c in parsed["controlpoint"]}["CPNAME_DP_16_powerplant"]
        self.assertEqual(cp["tpl"]["props"]["controlpointid"], "401")        # adopted from the reference
        self.assertEqual(cp["pos"], (-92.278, 153.181, -260.845))            # value from the demo

    @needs_layouts
    def test_static_text_is_the_retail_text_only_numbers_change(self):
        retail = layout_text("dalian_plant", "gpm_cq", 16).split("\n")
        ours = export_gameplay_objects(replay("auto_rot_12_10_07.bf2demo")).split("\n")
        ours = ours[:ours.index("rem ********** bf2demo parser notes **********")]
        mask = lambda l: re.sub(r"-?\d+(\.\d+)?", "#", l.replace(" (bf2demo parser)", ""))  # noqa: E731
        self.assertEqual([mask(l) for l in ours][:len(retail) - 1], [mask(l) for l in retail][:len(retail) - 1])

    def test_reflects_custom_map_edits(self):
        """Recorded on a locally edited Dalian cq/16 (moved flag, moved+rotated emplacement, new emplacement, swapped type)."""
        parsed = _compare_con().parse(export_gameplay_objects(replay("custom_dalian16_edited.bf2demo")))
        cps = {c["name"]: c["pos"] for c in parsed["controlpoint"]}
        self.assertEqual(cps["CPNAME_DP_16_reactors"], (101.25, 153.17, -61.5))     # vanilla: 88/153.17/-40
        by_pos = {s["pos"]: s for s in parsed["objectspawner"]}
        moved = by_pos[(-90.5, 155.204, -247.25)]                                     # vanilla: -93.745/.../-245.007
        self.assertEqual((moved["rot"][0], moved["tpl"]["slots"][1]), (100.0, "ats_hj8"))
        added = by_pos[(-70.125, 154.0, -240.5)]                                      # not in vanilla
        self.assertEqual(added["rot"][0], 33.333)
        self.assertIn("ats_tow", added["tpl"]["slots"].values())                     # a further instance of an existing template
        swapped = by_pos[(-109.697, 153.2, -327.735)]                                 # vanilla: ARS_D30
        self.assertEqual(swapped["tpl"]["slots"][1], "ats_hj8")


class StaticObjectsExportTest(unittest.TestCase):
    def test_kubra_dam_matches_the_retail_static_objects(self):
        """Values copied from Kubra Dam's retail StaticObjects.con: destructible statics arrive with their exact file transform."""
        blocks = parse_static_blocks(export_static_objects(replay("test_kubra16.bf2demo")))
        self.assertEqual(len(blocks), 35)
        self.assertIn(("barrel_yellow", "-267.884/69.530/-9.302", ""), blocks)
        self.assertIn(("barrel_yellow", "-247.992/69.316/-10.605", "-171.0/89.1/-171.0"), blocks)
        self.assertEqual(sorted({b[0] for b in blocks}),
                         ["barrel_yellow", "dam_bridge_part1", "dam_bridge_part2", "dam_bridge_part3", "dam_ironbridge_part1",
                          "dam_ironbridge_part2", "dam_ironbridge_part3", "fueltankwagon", "sign_author_perso", "trestle01_dest",
                          "woodencrate_destructible_medical"])

    def test_wake_island_wooden_parts_are_present(self):
        names = {b[0] for b in parse_static_blocks(export_static_objects(replay("map_wake_island_2007.bf2demo")))}
        self.assertTrue(names)
        self.assertTrue(any("bridge" in n or "crate" in n or "wood" in n for n in names), names)


class JsonAndTracksTest(unittest.TestCase):
    def test_json_export_matches_the_text_outputs(self):
        rep = replay("zxc.bf2demo")
        doc = json.loads(json.dumps(build_document(rep)))
        self.assertEqual(doc["format"], "bf2demo-json/2")
        self.assertEqual([f["text"] for f in doc["feed"]], [line.text for line in build_feed(rep, verbose=True)])
        self.assertEqual(len(doc["scoreboard"]), len(build_scoreboard(rep)))
        self.assertEqual(doc["demo"]["map"], rep.demo.header.map_name)
        self.assertTrue(doc["tickets"])
        self.assertGreater(len(doc["objects"]), 100)

    def test_tracks_start_at_the_creation_position(self):
        tracks = build_tracks(replay("bf2rangers001.bf2demo"))
        soldiers = [t for t in tracks.values() if t.obj.template.cls == "Soldier" and t.obj.created_tick > 0 and t.obj.position]
        self.assertGreater(len(soldiers), 100)
        close = sum(1 for t in soldiers if math.dist(t.obj.position, t.samples[0][1]) < 1.0)
        self.assertGreaterEqual(close / len(soldiers), 0.95)       # absolute float positions, no baseline needed

    def test_vehicle_parts_are_converted_to_physical_units(self):
        tracks = build_tracks(replay("zxc.bf2demo"), projectiles=False, parts=True)
        angles = []
        seat_rows = engine_rows = 0
        for track in tracks.values():
            for _tick, scope, _element, kind, values in track.parts:
                if kind == "R":
                    angles.extend(v for k, v in values.items() if k.startswith("rot_"))
                    seat_rows += scope > 0
                elif kind == "E" and "rpm_a" in values:
                    engine_rows += 1
        self.assertGreater(len(angles), 1000)
        self.assertTrue(all(-180.0 <= a <= 180.0 for a in angles))
        self.assertGreater(seat_rows, 100)       # turret / gunner seat ghosts
        self.assertGreater(engine_rows, 100)


if __name__ == "__main__":
    unittest.main()
