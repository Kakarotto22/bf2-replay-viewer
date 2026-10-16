"""What makes the page load fast on a phone: the light HD map, the minimap as a JPEG, the map name in a header, cacheable maps."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import time
import unittest

from bf2demo.web.app import create_app

from .common import sample_path

SAMPLE = "claude_spawn_115014.bf2demo"


class LoadingTest(unittest.TestCase):
    def setUp(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        self.Image = Image
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.maps = os.path.join(self.tmp, "maps")
        self.demos = os.path.join(self.tmp, "demos")
        os.makedirs(self.maps), os.makedirs(self.demos)
        shutil.copy(sample_path(SAMPLE), self.demos)
        Image.new("RGB", (4096, 4096), (90, 120, 60)).save(os.path.join(self.maps, "testlevel.jpg"), "JPEG", quality=70)
        self.client = create_app([self.demos], os.path.join(self.tmp, "cache"), map_folders=[self.maps], donate_file=False).test_client()

    def test_the_hd_map_comes_in_a_light_2048_version_for_phones(self):
        full = self.client.get("/api/maps/testlevel/hd.jpg")
        light = self.client.get("/api/maps/testlevel/hd.jpg?size=2048")
        self.assertEqual((full.status_code, light.status_code), (200, 200))
        self.assertEqual(max(self.Image.open(io.BytesIO(light.data)).size), 2048)
        self.assertEqual(self.Image.open(io.BytesIO(full.data)).size, (4096, 4096))            # the full map is untouched
        self.assertIn("max-age=3600", light.headers["Cache-Control"])                              # maps may be cached (browser, Cloudflare)
        self.assertIn("max-age=3600", full.headers["Cache-Control"])
        again = self.client.get("/api/maps/testlevel/hd.jpg?size=2048", headers={"If-None-Match": light.headers["ETag"]})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(self.client.get("/api/maps/testlevel/hd.jpg?size=999999").status_code, 200)   # any other size = the normal map, never a custom resize
        self.assertEqual(self.client.get("/api/maps/nolevel/hd.jpg?size=2048").status_code, 404)

    def test_the_map_name_is_in_a_header_of_the_document(self):
        did = self.client.get("/api/demos").get_json()[0]["id"]
        self.client.get(f"/api/demos/{did}")
        for _ in range(240):                                                                        # the parse runs in a thread
            reply = self.client.get(f"/api/demos/{did}")
            if reply.status_code == 200:
                break
            time.sleep(0.5)
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.headers["X-Demo-Map"], "dalian_plant")

    def test_the_minimap_jpeg_route_works_with_the_game_and_is_a_404_without_it(self):
        reply = self.client.get("/api/maps/dalian_plant.jpg")
        self.assertIn(reply.status_code, (200, 404))                                                  # 200 only where the game is installed
        if reply.status_code == 200:
            self.assertEqual(reply.mimetype, "image/jpeg")
            self.assertLess(len(reply.data), 150_000)
        self.assertEqual(self.client.get("/api/maps/..%2f..%2fx.jpg").status_code, 404)


if __name__ == "__main__":
    unittest.main()
