"""Writing recordings: byte-exact round trip, end cuts, squashed start cuts (their invariants), and the clip download endpoint."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from bf2demo.clip import make_clip, serialize
from bf2demo.reader import inflate, load_demo, parse_stream
from bf2demo.replay import build_replay
from bf2demo.web.app import create_app

from .common import SAMPLES, sample_path

NAME = "claude_spawn_115014.bf2demo"


def reread(data: bytes):
    stream, recovered = inflate(data)
    assert not recovered
    return parse_stream(stream)


def state(replay):
    """What a viewer would show at the end: players, control point owners, tickets, live objects."""
    return {
        "players": sorted((p.player_id, p.name, p.team) for p in replay.player_history),
        "cps": sorted((cp.object_id, cp.team) for cp in replay.control_points.values()),
        "tickets": {team: history[-1][1] for team, history in replay.tickets.items() if history},     # the value, not the packet tick it arrived at
        "objects": sorted((o.object_id, o.template.name if o.template else None) for o in replay.objects.values()),
    }


class ClipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = sample_path(NAME)
        cls.demo = load_demo(cls.path)
        cls.ticks = [p.tick for p in cls.demo.packets if p.tick >= 0]
        cls.lo, cls.hi = min(cls.ticks), max(cls.ticks)

    def test_identity_round_trip_is_byte_exact(self):
        with open(self.path, "rb") as fh:
            stream, recovered = inflate(fh.read())
        self.assertFalse(recovered)
        self.assertEqual(serialize(self.demo), stream)

    def test_end_cut_keeps_a_prefix_untouched(self):
        end = (self.lo + self.hi) // 2
        clip = reread(make_clip(self.demo, end_tick=end))
        kept = [p for p in self.demo.packets if p.tick <= end]
        self.assertEqual([(p.tick, p.data) for p in clip.packets], [(p.tick, p.data) for p in kept])
        self.assertEqual(clip.header, self.demo.header)

    def test_start_cut_changes_header_ticks_only(self):
        start = self.lo + (self.hi - self.lo) * 2 // 3
        clip = reread(make_clip(self.demo, start_tick=start, lead_seconds=4))
        self.assertEqual(len(clip.packets), len(self.demo.packets))
        self.assertTrue(all(a.data == b.data for a, b in zip(clip.packets, self.demo.packets)))          # payload bits never touched
        squash_until = start - 4 * 30
        for new, old in zip(clip.packets, self.demo.packets):
            if old.tick < 0 or old.tick >= squash_until:
                self.assertEqual(new.tick, old.tick)                                                    # join packets and the clip keep their ticks
            else:
                self.assertEqual(new.tick, squash_until)                                                # the pre-roll is applied at once
        positives = [p.tick for p in clip.packets if p.tick >= 0]
        self.assertEqual(positives, sorted(positives))                                                 # the clock never runs backwards

    def test_start_cut_replays_to_the_same_final_state(self):
        start = self.lo + (self.hi - self.lo) // 2
        clip = reread(make_clip(self.demo, start_tick=start, lead_seconds=2))
        self.assertEqual(state(build_replay(clip)), state(build_replay(self.demo)))

    def test_end_cut_before_the_round_start_is_still_a_valid_file(self):
        clip = reread(make_clip(self.demo, end_tick=self.lo))
        self.assertTrue(clip.packets and all(p.tick <= self.lo for p in clip.packets))


class ClipEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = sample_path(NAME)
        cls.tmp = tempfile.mkdtemp()
        cls.folder = os.path.join(cls.tmp, "demos")
        os.makedirs(cls.folder)
        shutil.copy(src, os.path.join(cls.folder, "a.bf2demo"))
        cls.client = create_app([cls.folder], os.path.join(cls.tmp, "cache")).test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_download_is_a_valid_recording_with_a_safe_name(self):
        did = self.client.get("/api/demos").get_json()[0]["id"]
        demo = load_demo(os.path.join(SAMPLES, NAME))
        ticks = [p.tick for p in demo.packets if p.tick >= 0]
        end = min(ticks) + (max(ticks) - min(ticks)) // 2
        response = self.client.get(f"/api/demos/{did}/clip?end={end}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertRegex(response.headers["Content-Disposition"], r'filename="[A-Za-z0-9_\-]+\.bf2demo"')
        self.assertEqual(max(p.tick for p in reread(response.data).packets), end)
        self.assertEqual(self.client.get(f"/api/demos/{did}/clip?start={end}&end={end - 10}").status_code, 400)
        self.assertEqual(self.client.get("/api/demos/0123456789abcdef/clip").status_code, 404)


if __name__ == "__main__":
    unittest.main()
