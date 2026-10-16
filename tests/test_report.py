"""The readable report: section registry, clock times and the tick rate evidence."""

import unittest

from bf2demo import report
from bf2demo.timeline import TICKS_PER_SECOND, format_span, format_tick
from tests.common import replay


class TimelineTests(unittest.TestCase):
    def test_format_span(self):
        self.assertEqual(format_span(0), "00:00")
        self.assertEqual(format_span(72000), "40:00")
        self.assertEqual(format_span(3600 * TICKS_PER_SECOND + 61 * TICKS_PER_SECOND), "1:01:01")

    def test_lobby_ticks_have_no_clock(self):
        self.assertEqual(format_tick(-1, 30), "--:--")
        self.assertEqual(format_tick(60, 30), "00:01")

    def test_tick_rate_matches_the_vote_timeout(self):
        """A vote runs out 90 s after it starts: 2701 ticks between the two Vote events of this sample."""
        rep = replay("auto_2026_08_01_00_36_33.bf2demo")
        votes = [(t, ev["time_remaining"]) for t, ev in rep.events if ev.name == "Vote"]
        start = next(t for t, remaining in votes if remaining == 90.0)
        end = next(t for t, remaining in votes if t > start and remaining == 0.0)
        self.assertAlmostEqual((end - start) / TICKS_PER_SECOND, 90.0, delta=0.1)


class ReportTests(unittest.TestCase):
    def test_every_section_renders(self):
        text = report.render(replay("bf2rangers001.bf2demo"))
        for sec in report.SECTIONS.values():
            self.assertIn(f"== {sec.title} ==", text)
        self.assertIn("40:00 later", text)           # the time limit of a 40 minute server round

    def test_selection_and_unknown_section(self):
        rep = replay("map_dalian_plant.bf2demo")
        self.assertTrue(report.render(rep, ["overview"]).startswith("== Overview =="))
        with self.assertRaises(KeyError):
            report.render(rep, ["nope"])

    def test_a_section_can_be_registered_once(self):
        with self.assertRaises(ValueError):
            report.section("overview", "again")(lambda rep: [])


class RadioTests(unittest.TestCase):
    def test_radio_calls_are_counted_per_player(self):
        text = report.render(replay("bf2rangers001.bf2demo"), ["radio"])
        self.assertIn("medic", text)
        self.assertIn("never appear in a recording", text)


class SquadAndCommanderTests(unittest.TestCase):
    def test_squads_commander_and_ending_sections_render(self):
        rep = replay("bf2rangers001.bf2demo")
        text = report.render(rep, ["squads", "commander"])
        self.assertIn("squad", text)
        self.assertIn("UAV", text)

    def test_invites_and_the_inferred_ending_on_a_two_day_recording(self):
        """Wake Island 2026-10-13 22:48 (needs samples/rangers2days, not in git): immortal was invited by squad 1 twice; CH lost on tickets."""
        rep = replay("rangers2days/wake_island_2007_20261013-2248_13h.bf2demo")
        immortal = next(p for p in rep.player_history if p.name.strip() == "immortal")
        self.assertEqual([m for _, m in immortal.invite_history if m], [2, 2])         # bit 1 = squad 1
        text = report.render(rep, ["overview"])
        self.assertIn("tickets of CH were down to 5", text)
        self.assertIn("6 of 6 flags", text)


class ServerInfoTests(unittest.TestCase):
    def test_server_settings_match_the_known_test_server_config(self):
        """``RE_Claude`` ran with 3 rounds per map, spawn time 15, ticket ratio 100 and no time limit (its ServerSettings file)."""
        info = replay("map_dalian_plant.bf2demo").server_info
        self.assertEqual((info["server_name"], info["rounds_per_map"], info["spawn_time"], info["ticket_ratio"], info["time_limit"]),
                         ("RE_Claude", 3, 15, 100, 0))
        self.assertEqual((info["voip_server_port"], info["voip_bf_client_port"], info["voip_quality"], info["gamespy_port"]),
                         (55125, 55123, 3, 29900))

    def test_rangers_round_has_a_welcome_message_and_a_time_limit_in_the_report(self):
        rep = replay("bf2rangers001.bf2demo")
        self.assertIn("WELCOME", rep.server_info["welcome_message"][0])
        self.assertIn("Welcome message", report.render(rep, ["settings"]))


class RegistrationTests(unittest.TestCase):
    def test_register_event_adds_a_readable_kind(self):
        from bf2demo import events
        from bf2demo.bitstream import BitStream
        old_names, old_readers = dict(events.EVENT_NAMES), dict(events._READERS)
        try:
            events.register_event(99, "TestEvent", lambda bs: {"value": bs.read_bits(8)})
            width = events.EID_BITS
            data = (99 | (0xAB << width)).to_bytes(4, "little")
            ev = events.read_event(BitStream(data))
            self.assertEqual((ev.name, ev["value"]), ("TestEvent", 0xAB))
        finally:
            events.EVENT_NAMES.clear(); events.EVENT_NAMES.update(old_names)
            events._READERS.clear(); events._READERS.update(old_readers)


if __name__ == "__main__":
    unittest.main()
