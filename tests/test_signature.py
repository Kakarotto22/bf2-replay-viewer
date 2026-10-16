"""The welcome-message signature of clips, the kill message labels and the wreck tick of vehicles."""

from __future__ import annotations

import os
import unittest

from bf2demo.clip import make_clip
from bf2demo.feed import build_feed
from bf2demo.packet import parse_packet
from bf2demo.reader import inflate, load_demo, parse_stream
from bf2demo.replay import build_replay
from bf2demo.signature import SIGNATURE_LINES, sign_packet
from bf2demo.tracks import build_tracks

from .common import SAMPLES, replay, sample_path

NAME = "claude_spawn_115014.bf2demo"


class SignatureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = load_demo(sample_path(NAME))
        stream, _ = inflate(make_clip(cls.demo, signature=True))
        cls.signed = parse_stream(stream)

    def test_message_is_in_every_settings_block_and_nothing_else_changes(self):
        base, signed = build_replay(self.demo), build_replay(self.signed)
        self.assertEqual(signed.server_info["welcome_message"], list(SIGNATURE_LINES))
        keep = {k: v for k, v in base.server_info.items() if k != "welcome_message"}
        self.assertEqual({k: v for k, v in signed.server_info.items() if k != "welcome_message"}, keep)
        self.assertEqual(len(self.signed.packets), len(self.demo.packets))
        self.assertEqual(sorted((p.player_id, p.name, p.team) for p in signed.player_history), sorted((p.player_id, p.name, p.team) for p in base.player_history))
        self.assertEqual(signed.tickets, base.tickets)
        self.assertEqual(len(signed.packet_errors), len(base.packet_errors))

    def test_ghost_payloads_are_bit_identical(self):
        changed = 0
        for old, new in zip(self.demo.packets, self.signed.packets):
            self.assertEqual(old.tick, new.tick)
            if old.data == new.data or not old.data:
                continue
            changed += 1
            a, b = parse_packet(old.data), parse_packet(new.data)
            self.assertEqual([e.name for e in a.events if e.name != "DataBlock"], [e.name for e in b.events if e.name != "DataBlock"])
            for x, y in zip(a.ghosts, b.ghosts):
                bits = lambda pkt, g, data: [(int.from_bytes(data, "little") >> (g.bit_start + i)) & 1 for i in range(g.bit_length)]   # noqa: E731
                self.assertEqual((x.ghost_id, x.action, bits(a, x, old.data)), (y.ghost_id, y.action, bits(b, y, new.data)))
        self.assertGreaterEqual(changed, 1)

    def test_packet_without_a_settings_block_is_left_alone(self):
        for packet in self.demo.packets[:200]:
            if packet.data and sign_packet(packet.data) is None:
                return
        self.fail("no packet without a settings block found")


class KillLabelTest(unittest.TestCase):
    """The game's own log of ``zxc`` (OCR) is the reference: a bomb dropped by a pilot who has left the F-35B prints empty brackets."""

    @classmethod
    def setUpClass(cls):
        cls.lines = [l for l in build_feed(replay("zxc.bf2demo")) if l.kind in ("kill", "teamkill") and l.data]

    def test_vehicle_name_wins_for_a_vehicle_killer_and_weapon_name_for_a_soldier(self):
        labels = [l.data["weapon"] for l in self.lines]
        self.assertEqual(labels[0], "WZ-10")
        self.assertIn("Predator SRAW 'ATGM'", labels)
        self.assertIn("M4A1 'Carbine'", labels)

    def test_no_placeholder_text_is_ever_shown(self):
        for line in self.lines:
            self.assertNotIn("DELETED", line.text.upper())
            self.assertIsNotNone(line.data["weapon"])


RANGERS = os.path.join(SAMPLES, "rangers2days", "zatar_wetlands_20261013-2002_14h.bf2demo")


@unittest.skipUnless(os.path.isfile(RANGERS), "rangers recording not present")
class WreckTest(unittest.TestCase):
    def test_wreck_tick_is_when_the_crew_dies(self):
        rep = build_replay(load_demo(RANGERS))
        tracks = build_tracks(rep, projectiles=False)
        deaths = [(t, ev["victim_id"]) for t, ev in rep.events if ev.name == "KilledBy"]
        wrecked = [t for t in tracks.values() if t.wrecked_tick is not None]
        self.assertGreater(len(wrecked), 20)
        for t in wrecked:
            self.assertLess(t.wrecked_tick, t.obj.destroyed_tick or 10 ** 9)       # the wreck burns for seconds before the object is removed
        matched = sum(1 for t in wrecked if any(abs(tick - t.wrecked_tick) <= 2 for tick, _ in deaths))
        self.assertGreaterEqual(matched, 8)                                          # 11 of the vehicles that held a crew killed it at that very tick


if __name__ == "__main__":
    unittest.main()


class HeldWeaponTest(unittest.TestCase):
    """``weapon_item_index`` of the soldier ghost against the kits' slot table (``scripts/build_weapon_slots.py``): the weapon that killed is
    the weapon in hand for most hand-weapon kills (the rest are thrown grenades, mines and weapon changes just before the kill)."""

    def test_item_index_names_the_killing_weapon(self):
        import bisect
        import json
        from bf2demo.feed import team_name
        rep = replay("zxc.bf2demo")
        tracks = [t for t in build_tracks(rep, projectiles=False).values() if t.items and t.owner_id is not None]
        with open(os.path.join(os.path.dirname(__file__), "..", "bf2demo", "assets", "weapon_slots.json"), encoding="utf-8") as fh:
            kits = json.load(fh)["kits"]
        every = {w for slots in kits.values() for names in slots.values() for w in names}
        kit_names = ["specops", "sniper", "assault", "support", "engineer", "medic", "at"]
        hit = miss = 0
        for tick, ev in rep.events:
            if ev.name != "KilledBy" or not ev["has_killer"] or not ev["weapon_template_id"]:
                continue
            weapon = rep.templates.lookup(ev["weapon_template_id"]).name.lower()
            player = next((p for p in rep.player_history if p.player_id == ev["attacker_id"]), None)
            if weapon not in every or player is None:
                continue
            owned = [t for t in tracks if t.owner_id == player.player_id and t.items[0][0] <= tick]
            if not owned:
                continue
            items = max(owned, key=lambda t: t.items[0][0]).items
            i = bisect.bisect_right([t for t, _ in items], tick) - 1
            kit = [k for t, k in player.kit_history if t <= tick][-1:]
            if i < 0 or not kit:
                continue
            key = f"{team_name(rep, player.team_at(tick)).lower()}_{kit_names[kit[0]]}"
            if weapon in kits.get(key, {}).get(str(items[i][1]), []):
                hit += 1
            else:
                miss += 1
        self.assertGreaterEqual(hit, 15)
        self.assertGreater(hit, 3 * miss)                               # 20 of 24 on zxc; chance would be about one in five
