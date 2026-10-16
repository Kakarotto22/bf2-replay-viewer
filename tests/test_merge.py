"""Merging several recordings of one map for --export-con."""

import re
import re
import unittest

from bf2demo.export_con import ExportOptions, export_gameplay_objects
from bf2demo.export_observe import observe
from bf2demo.merge import merge_replays
from tests.common import replay


class MergeTests(unittest.TestCase):
    def test_different_maps_are_refused(self):
        with self.assertRaises(ValueError):
            merge_replays([replay("map_dalian_plant.bf2demo"), replay("map_kubra_dam.bf2demo")])

    def test_one_replay_is_returned_unchanged(self):
        rep = replay("map_dalian_plant.bf2demo")
        self.assertIs(merge_replays([rep]), rep)

    def test_kit_spawns_of_every_demo_count_together(self):
        """A position that two soldiers spawned at in two different recordings is a spawn point."""
        rep = replay("zxc.bf2demo")
        merged = merge_replays([rep, rep])
        self.assertEqual(len(merged.kit_spawns), 2 * len(rep.kit_spawns))
        opt = ExportOptions(min_spawn_count=2)
        single = {p.position[:1] + p.position[2:]: p.count for p in observe(rep, opt)[2]}
        both = {p.position[:1] + p.position[2:]: p.count for p in observe(merged, opt)[2]}
        self.assertTrue(set(single) <= set(both))
        self.assertTrue(all(both[k] == 2 * single[k] for k in single))
        self.assertGreater(len(both), len(single))      # positions seen once per demo are now repeated

    def test_sites_merge_by_transform_and_exact_absorbs_snapshot(self):
        a, b = replay("auto_all_vehicles_dalian16.bf2demo"), replay("map_dalian_plant.bf2demo")
        merged = merge_replays([a, b])
        self.assertLessEqual(len(merged.spawn_sites), len(a.spawn_sites) + len(b.spawn_sites))
        self.assertGreaterEqual(sum(s.exact for s in merged.spawn_sites), sum(s.exact for s in a.spawn_sites))
        self.assertEqual(len(merged.merged_from), 2)

    def test_second_demo_is_resolved_with_its_own_flag_owners(self):
        """Merging a demo with itself must not change what any spawner resolves to (flags change hands in this one)."""
        rep = replay("bf2rangers001.bf2demo")
        merged = merge_replays([rep, rep])
        opt = ExportOptions()

        def resolved(r):
            return {tuple(round(c, 2) for c in ds.position): (sorted(ds.slots.items()), sorted(ds.unknown_team))
                    for ds in observe(r, opt)[1]}
        single, both = resolved(rep), resolved(merged)
        self.assertTrue(set(single) <= set(both))
        # (a second sighting of a lone creation makes it "confirmed", so the merge may add spawners, never change one)
        self.assertEqual({k: both[k] for k in single}, single)

    def test_export_of_a_merge_names_its_sources(self):
        merged = merge_replays([replay("map_dalian_plant.bf2demo"), replay("test2.bf2demo")])
        text = export_gameplay_objects(merged, ExportOptions())
        flat = " ".join(line[3:].strip() if line.startswith("rem") else line for line in text.splitlines())   # notes are wrapped
        self.assertIn("merged with 1 more recording(s)", flat)


if __name__ == "__main__":
    unittest.main()
