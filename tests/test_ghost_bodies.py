"""Ghost bodies: every decoder must consume its records exactly (the evidence the layouts are right)."""

from __future__ import annotations

import collections
import unittest

from bf2demo.bitstream import BitStream
from bf2demo.coverage import GhostOwners, analyse, decode_ghost_body
from bf2demo.networkables import decode_player
from bf2demo.objectnet import (SimpleObjectContext, decode_child_pco, decode_generic_projectile, decode_simple_object,
                               decode_soldier, decode_vehicle)
from bf2demo.templatedb import _load

from .common import all_samples, ghost_updates, replay


class CoverageTest(unittest.TestCase):
    def test_every_ghost_body_of_every_sample_is_explained_exactly(self):
        """The headline guarantee: no unexplained bit in any sample (set BF2DEMO_SLOW=1 to include the large full rounds)."""
        for name in all_samples():
            report = analyse(replay(name))
            self.assertEqual(report.undecoded_records[:3], [], name)
            self.assertGreater(report.understood_ratio, 0.9999, name)


class SingleClassTest(unittest.TestCase):
    def test_player_ghost_records(self):
        rep = replay("zxc.bf2demo")
        ghost_ids = {p.ghost_id for p in rep.player_history}
        checked = 0
        for packet, g in ghost_updates(rep):
            if g.ghost_id in ghost_ids:
                self.assertEqual(decode_player(packet.data, g.bit_start).bits, g.bit_length)
                checked += 1
        self.assertGreater(checked, 8000)

    def test_soldier_bodies(self):
        rep = replay("zxc.bf2demo")
        n = 0
        for packet, g in ghost_updates(rep, start_tick=0):
            obj = rep.object_at(g.ghost_id, packet.tick)
            if obj is not None and obj.template.cls == "Soldier":
                self.assertEqual(decode_soldier(BitStream(packet.data, g.bit_start)).bits, g.bit_length)
                n += 1
        self.assertGreater(n, 30000)

    def test_projectile_and_supply_bodies(self):
        rep = replay("bf2rangers002.bf2demo")
        checked = collections.Counter()
        for packet, g in ghost_updates(rep):
            obj = rep.object_at(g.ghost_id, packet.tick)
            if obj is None:
                continue
            t = obj.template
            bs = BitStream(packet.data, g.bit_start)
            if t.cls == "GenericProjectile":
                self.assertEqual(decode_generic_projectile(bs, t.range_bits).bits, g.bit_length, (t.name, packet.tick))
            elif t.cls in ("SupplyObject", "UAVVehicle"):
                self.assertEqual(decode_simple_object(bs, SimpleObjectContext(True, t.range_bits)).bits, g.bit_length)
            else:
                continue
            checked[t.cls] += 1
        self.assertGreater(checked["GenericProjectile"], 50000)


class VehicleTest(unittest.TestCase):
    def test_sequences_are_derived_from_the_template_tree(self):
        """Rotors are SimpleObject networkables (O), equal engines/wings merge into one group, wings that differ in
        setAutomaticReset or rotation limits stay separate."""
        seq = {e[1]: (e[5] if len(e) > 5 else None) for e in _load()["global"]}
        self.assertEqual(seq["ahe_ah1z"], "OORREE")
        self.assertEqual(seq["boat_rib"], "RRRRERRR")
        self.assertEqual(seq["usair_f18"], "RRRRER")
        self.assertEqual(seq["usthe_uh60"], "EEOORRE")

    def test_helicopter_and_tank_bodies_of_a_full_round(self):
        rep = replay("bf2rangers002.bf2demo")
        total = collections.Counter()
        for packet, g in ghost_updates(rep):
            obj = rep.object_at(g.ghost_id, packet.tick)
            if obj is not None and obj.template.cls == "PlayerControlObject" and obj.template.netseq is not None:
                self.assertEqual(decode_vehicle(BitStream(packet.data, g.bit_start), obj.template), g.bit_length,
                                 (obj.template.name, packet.tick))
                total[obj.template.name] += 1
        self.assertGreater(sum(total.values()), 100000)
        self.assertTrue({"the_mi17", "usthe_uh60", "rutnk_t90", "ustnk_m1a2"} <= set(total))

    def test_nested_pco_and_parachute_bodies(self):
        """Ghost ``root id + 1 + index`` is a nested PlayerControlObject: weapon block + own sequence (turret seats) or the
        occupant soldier (passenger seats); parachutes are SimpleObject + wings."""
        rep = replay("zxc.bf2demo")
        nested = parachutes = 0
        for packet, g in ghost_updates(rep):
            bs = BitStream(packet.data, g.bit_start)
            obj = rep.object_at(g.ghost_id, packet.tick)
            if obj is not None:
                if obj.template.cls == "Parachute":
                    self.assertEqual(decode_vehicle(bs, obj.template), g.bit_length)
                    parachutes += 1
                continue
            owner = rep.nested_owner(g.ghost_id, packet.tick)
            if owner is not None:
                self.assertEqual(decode_child_pco(bs, owner[0].template, owner[1]), g.bit_length)
                nested += 1
        self.assertGreater(nested, 1000)
        self.assertGreater(parachutes, 500)

    def test_every_vehicle_template_is_explained_exactly(self):
        """The demos made with scripts/make_vehicle_test_zip.py hold one of every PlayerControlObject template of the base game
        (Dalian), of Special Forces (Surge) and of the booster pack (Midnight Sun), including templates no round sample has."""
        for name, minimum in (("auto_all_vehicles_dalian16.bf2demo", 45), ("auto_all_vehicles_xpack_surge16.bf2demo", 55),
                              ("auto_all_vehicles_booster_midnight_sun16.bf2demo", 55)):
            rep = replay(name)
            owners = GhostOwners(rep)
            seen = set()
            for packet, g in ghost_updates(rep):
                obj = rep.object_at(g.ghost_id, packet.tick)
                if obj is not None and obj.template.netseq is not None:
                    self.assertEqual(decode_ghost_body(owners, g, packet.data, packet.tick), g.bit_length,
                                     (name, obj.template.name, packet.tick))
                    seen.add(obj.template.name)
            self.assertGreaterEqual(len(seen), minimum, name)


class MapPartsTest(unittest.TestCase):
    def test_special_forces_elevators_are_decoded(self):
        rep = replay("auto_xpack_surge16.bf2demo")
        classes = {o.template.cls for o in rep.object_history}
        self.assertIn("TriggerableTarget", classes)
        self.assertIn("Triggerable", classes)
        self.assertTrue(analyse(rep).complete)


if __name__ == "__main__":
    unittest.main()
