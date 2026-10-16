"""Web viewer: compact track encoding, library/cache API and the safety of the endpoints."""

from __future__ import annotations

import gzip
import json
import math
import os
import shutil
import tempfile
import time
import unittest

from bf2demo.web import maps
from bf2demo.web.app import create_app
from bf2demo.web.viewer_format import FORMAT, GAP_TICKS, STEP, build_viewer_document, heading_degrees, seat_intervals

from .common import SAMPLES, replay, sample_path

SAMPLE = "claude_spawn_115014.bf2demo"


def decode(track):
    """Mirror of ``decodeTrack`` in app.js: absolute ticks and decimetre positions back from deltas."""
    tick, x, y, z = track["t0"], 0, 0, 0
    out = []
    for dt, dx, dy, dz, h in zip(track["dt"], track["x"], track["y"], track["z"], track["h"]):
        tick, x, y, z = tick + dt, x + dx, y + dy, z + dz
        out.append((tick, x / 10, y / 10, z / 10, h))
    return out


class HeadingTest(unittest.TestCase):
    def test_axes(self):
        self.assertEqual(heading_degrees((0, 0, 0, 1)), 0)                     # identity faces +z (north)
        s = math.sin(math.radians(45))
        self.assertEqual(heading_degrees((0, s, 0, s)), 270)                   # the stored quaternion is the inverse: +90 about y faces west
        self.assertEqual(heading_degrees((0, -s, 0, s)), 90)
        self.assertEqual(heading_degrees((0, 1, 0, 0)), 180)
        self.assertIsNone(heading_degrees(None))


class SoldierHeadingTest(unittest.TestCase):
    def test_track_rotation_of_a_soldier_reads_back_as_its_yaw(self):
        from bf2demo.tracks import _yaw_quaternion
        for yaw in (-270.0, -135.0, -90.0, 0.0, 45.0, 90.0, 180.0, 300.0):
            self.assertEqual(heading_degrees(_yaw_quaternion(yaw)), round(yaw) % 360, yaw)


class ViewerDocumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sample_path(SAMPLE)
        cls.rep = replay(SAMPLE)
        cls.doc = build_viewer_document(cls.rep)

    def test_tracks_are_decimated_and_round_trip(self):
        from bf2demo.tracks import build_tracks
        full = build_tracks(self.rep, projectiles=False)
        by_id = {(t.obj.object_id, t.samples[0][0]): t for t in full.values() if t.samples}      # ids are reused over a round
        self.assertTrue(self.doc["tracks"])
        for track in self.doc["tracks"]:
            samples = decode(track)
            source = by_id[(track["id"], track["t0"])].samples
            self.assertLessEqual(len(samples), len(source))
            self.assertEqual(samples[0][0], source[0][0])
            self.assertEqual(samples[-1][0], source[-1][0])                    # the last sample is always kept
            for a, b, c in zip(samples, samples[1:], samples[2:]):             # extra samples are only kept right before a gap
                self.assertTrue(b[0] - a[0] >= STEP or c[0] - b[0] > GAP_TICKS, (a[0], b[0], c[0]))
            tick, pos, _ = source[0]
            self.assertAlmostEqual(samples[0][1], pos[0], delta=0.051)         # decimetre quantisation
            self.assertAlmostEqual(samples[0][3], pos[2], delta=0.051)

    def test_vehicle_heading_follows_the_movement_direction(self):
        """The facing of driving vehicles must match where they go (this caught the inverse quaternion): resultant length >= 0.8 near 0."""
        sin = cos = n = 0.0
        for track in self.doc["tracks"]:
            if track["cls"] != "PlayerControlObject":
                continue
            samples = decode(track)
            for a, b in zip(samples, samples[1:]):
                dx, dz = b[1] - a[1], b[3] - a[3]
                if a[4] < 0 or math.hypot(dx, dz) < 1.5 or b[0] - a[0] > 90:
                    continue
                off = math.radians(math.degrees(math.atan2(dx, dz)) - a[4])
                sin, cos, n = sin + math.sin(off), cos + math.cos(off), n + 1
        if n < 30:
            self.skipTest("too little vehicle motion in this sample")
        self.assertGreater(math.hypot(sin, cos) / n, 0.8)
        self.assertLess(abs(math.degrees(math.atan2(sin, cos))), 10)

    def test_strikes_are_landed_artillery_barrages_only(self):
        """No bombs, no shells left over from the join snapshot, no shells still in flight when the recording ended."""
        strikes = self.doc["strikes"]
        self.assertTrue(all(s["kind"] == "artillery" for s in strikes))
        self.assertTrue(all(s["t0"] > self.rep.first_tick + 1 and s["t1"] < self.rep.last_tick for s in strikes))

    def test_no_projectiles_and_document_extras(self):
        self.assertNotIn("GenericProjectile", {t["cls"] for t in self.doc["tracks"]})
        self.assertEqual(self.doc["ticks_per_second"], 30)
        self.assertEqual(len(self.doc["kit_names"]), 7)
        self.assertIn("1", self.doc["team_names"])


class SeatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sample_path("zxc.bf2demo")
        cls.rep = replay("zxc.bf2demo")
        cls.seats = seat_intervals(cls.rep)

    def test_seats_are_sequential_per_player_and_name_vehicles(self):
        self.assertTrue(self.seats)
        by_player = {}
        for seat in self.seats:
            self.assertTrue(seat["b"] is None or seat["b"] >= seat["a"], seat)
            by_player.setdefault(seat["p"], []).append(seat)
        for player, seats in by_player.items():                             # a player sits in one place at a time
            for a, b in zip(seats, seats[1:]):
                self.assertTrue(a["b"] is not None and a["b"] <= b["a"], (player, a, b))
        classes = {o.template.cls for o in self.rep.object_history if o.object_id in {s["o"] for s in self.seats}}
        self.assertEqual(classes, {"PlayerControlObject", "Parachute"})      # never a Soldier object (that is a spawn)

    def test_switching_to_the_gunner_seat_keeps_the_helicopter_crewed(self):
        """Pilot -> gunner is ExitVehicle + EnterVehicle of a nested seat object (id root + 1): that must stay a seat of the same vehicle."""
        ids = {o.object_id for o in self.rep.object_history if o.template and o.template.name == "ahe_z10"}
        mine = [s for s in self.seats if s["p"] == 255 and s["o"] in ids]
        self.assertGreaterEqual(len(mine), 3)                                   # 23336 .. 23845: pilot, gunner, pilot, gunner, pilot
        for a, b in zip(mine, mine[1:]):
            self.assertEqual(a["b"], b["a"], (a, b))                            # no gap in which the helicopter looks empty
        self.assertTrue(all(s["o"] == 1825 for s in mine))

    def test_player_255_is_a_real_player(self):
        self.assertIn(255, {s["p"] for s in self.seats})


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = sample_path(SAMPLE)
        cls.tmp = tempfile.mkdtemp()
        cls.demos = os.path.join(cls.tmp, "demos")
        os.makedirs(os.path.join(cls.demos, "sub"))
        shutil.copy(src, os.path.join(cls.demos, "sub", "a.bf2demo"))
        open(os.path.join(cls.demos, "notes.txt"), "w").close()
        cls.app = create_app([cls.demos], os.path.join(cls.tmp, "cache"))
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @unittest.skipUnless(maps.game_root(), "no game install")
    def test_asset_store_serves_from_disk_after_the_first_build(self):
        """The first request builds the level / table / font files in the store, a fresh app (no game state in memory) serves them from it."""
        first = self.client.get("/api/maps/dalian_plant").get_json()
        self.assertTrue(first["available"])
        self.assertEqual(self.client.get("/api/assets/tables").status_code, 200)
        self.assertEqual(self.client.get("/api/fonts/digitalNumbers.json").status_code, 200)
        self.assertEqual(self.client.get("/api/fonts/not_a_font.json").status_code, 404)
        again = create_app([self.demos], os.path.join(self.tmp, "cache")).test_client()
        self.assertEqual(again.get("/api/maps/dalian_plant").get_json(), first)
        self.assertEqual(again.get("/api/maps/dalian_plant.png").status_code, 200)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "cache", "game", "tables.json")))

    @unittest.skipUnless(maps.game_root(), "no game install")
    def test_ticket_rules_reproduce_the_observed_bleed(self):
        """dragon_valley (64): 10 flags of 12 area each, 10 tickets a minute: 9 flags against 1 loses 10 * (108 - 12) / 100 = 9.6 a minute,
        exactly the one ticket every 187.5 ticks seen in a recording of that map; 8 flags (96 < 100) do not bleed at all."""
        rules = maps.ticket_rules("dragon_valley")
        areas = rules["areas"]["gpm_cq/64"]
        self.assertEqual((len(areas), set(map(tuple, areas.values())), rules["loss"]), (10, {(12, 12)}, {"1": 10, "2": 10}))
        rate = lambda own, other: rules["loss"]["1"] * (other * 12 - own * 12) / 100 if other * 12 >= 100 and other > own else 0   # noqa: E731
        self.assertAlmostEqual(rate(1, 9), 9.6)
        self.assertEqual(rate(2, 8), 0)

    def test_flow_list_parse_fetch_and_upload(self):
        items = self.client.get("/api/demos").get_json()
        self.assertEqual([i["name"] for i in items], ["a.bf2demo"])
        self.assertEqual(items[0]["status"], "new")
        did = items[0]["id"]
        self.assertEqual(self.client.get(f"/api/demos/{did}").status_code, 202)        # starts parsing
        deadline = time.time() + 120
        while time.time() < deadline:
            response = self.client.get(f"/api/demos/{did}")
            if response.status_code == 200:
                break
            self.assertNotEqual(response.get_json().get("status"), "error", response.get_json())
            time.sleep(0.5)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Encoding"], "gzip")
        doc = json.loads(gzip.decompress(response.data))
        self.assertEqual(doc["format"], FORMAT)
        self.assertEqual(response.headers["Cache-Control"], "no-cache")                 # never serve a stale document after a format change
        again = self.client.get(f"/api/demos/{did}", headers={"If-None-Match": response.headers["ETag"]})
        self.assertEqual(again.status_code, 304)
        listed = self.client.get("/api/demos").get_json()[0]
        self.assertEqual(listed["status"], "ready")
        self.assertEqual(listed["summary"]["map"], doc["demo"]["map"])
        with open(os.path.join(SAMPLES, SAMPLE), "rb") as fh:                          # upload lands in the upload folder
            data = {"file": (fh, "up.bf2demo")}
            reply = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
            self.assertEqual(reply.status_code, 200)
        self.assertEqual(len(self.client.get("/api/demos").get_json()), 1)               # an upload is NOT listed for everybody ...
        self.assertEqual(self.client.get(f"/api/demos/{reply.get_json()['id']}").status_code, 202)   # ... but its link works

    def test_clients_cannot_name_paths(self):
        for bad in ("..", "../../etc/passwd", "%2e%2e%2fsecret", "0123456789abcdef"):
            self.assertEqual(self.client.get(f"/api/demos/{bad}").status_code, 404, bad)
            self.assertEqual(self.client.post(f"/api/demos/{bad}/parse").status_code, 404, bad)
        self.assertEqual(self.client.get("/static/../app.py").status_code, 404)

    def test_upload_rejects_other_files(self):
        data = {"file": (__import__("io").BytesIO(b"x"), "evil.exe")}
        self.assertEqual(self.client.post("/api/upload", data=data, content_type="multipart/form-data").status_code, 400)
        self.assertEqual(self.client.post("/api/upload").status_code, 400)

    def test_backdrop_endpoint_never_takes_a_path(self):
        self.assertEqual(self.client.get("/api/maps/..%2f..%2fx.png").status_code, 404)
        self.assertFalse(self.client.get("/api/maps/not_a_level").get_json()["available"])

    def test_hud_endpoint_serves_only_indexed_icons(self):
        for evil in ("..%2f..%2fInit.con", "nothing/here", "ingame%2f..%2f..%2fInit.con"):
            self.assertEqual(self.client.get(f"/api/hud/{evil}.png").status_code, 404, evil)
        if maps.game_root():
            ok = self.client.get("/api/hud/ingame/player/icons/minimap/mini_soldier.png")
            self.assertEqual((ok.status_code, ok.mimetype), (200, "image/png"))

    def test_custom_hd_map_wins_and_cannot_escape_its_folder(self):
        folder = os.path.join(self.tmp, "hdmaps")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "my_level.png"), "wb") as fh:
            fh.write(b"fake png bytes")
        app = create_app([self.demos], os.path.join(self.tmp, "cache2"), [folder])
        client = app.test_client()
        self.assertEqual(client.get("/api/maps/my_level/hd.jpg").data, b"fake png bytes")
        self.assertEqual(client.get("/api/maps/..%2fmy_level/hd.jpg").status_code, 404)

    def test_index_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/static/js/main.js").status_code, 200)


class MapsTest(unittest.TestCase):
    def test_hd_map_is_a_stitched_jpeg_with_the_levels_extent(self):
        if maps.game_root() is None:
            self.skipTest("no BF2 install")
        from PIL import Image
        data = maps.hd_map("dalian_plant", max_size=1024)
        self.assertEqual(data[:2], bytes([0xFF, 0xD8]))                 # JPEG
        self.assertEqual(Image.open(__import__("io").BytesIO(data)).size, (1024, 1024))
        self.assertIsNone(maps.hd_map("no_such_level"))

    def test_world_size_from_installed_level(self):
        if maps.game_root() is None:
            self.skipTest("no BF2 install")
        backdrop = maps.load_backdrop("dalian_plant")
        self.assertEqual(backdrop["world_size"], 2048.0)
        self.assertTrue(backdrop["png"].startswith(b"\x89PNG"))
        self.assertIsNone(maps.load_backdrop("no_such_level"))


if __name__ == "__main__":
    unittest.main()
