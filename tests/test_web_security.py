"""Security of the web viewer: no file outside its folders can be read or written, headers, decompression limit, no internal paths in messages."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
import zlib

from bf2demo import reader
from bf2demo.web.app import create_app
from bf2demo.web.assets import safe_icon_key


class WebSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.demos = os.path.join(self.tmp, "demos")
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(self.demos)
        os.makedirs(os.path.join(self.cache, "game", "hud"))
        with open(os.path.join(self.cache, "secret.png"), "wb") as fh:           # a PNG next to the store: reachable by a traversal
            fh.write(b"TOP-SECRET")
        with open(os.path.join(self.cache, "game", "hud", "ok.png"), "wb") as fh:
            fh.write(b"public icon")
        self.client = create_app([self.demos], self.cache, allow_upload=True, donate_file=False).test_client()

    def test_icon_names_cannot_leave_the_store(self):
        self.assertEqual(self.client.get("/api/hud/ok.png").data, b"public icon")             # the normal case still works
        for path in ("/api/hud/../../secret.png", "/api/hud/%2e%2e/%2e%2e/secret.png", "/api/hud/..%2f..%2fsecret.png", "/api/hud/..\..\secret.png",
                     "/api/hud/%2e%2e%5c%2e%2e%5csecret.png", "/api/hud/ok/../../../secret.png", "/api/hud//etc/passwd.png", "/api/hud/%00.png"):
            with self.subTest(path=path):
                reply = self.client.get(path)
                self.assertNotIn(b"TOP-SECRET", reply.data)
                self.assertIn(reply.status_code, (301, 308, 400, 404))
        for key in ("..", "a/../b", "/abs", "a//b", "a/./b", "x" * 300, "", "a\x00b", "a:b"):
            self.assertFalse(safe_icon_key(key), key)
        self.assertTrue(safe_icon_key("ingame/vehicles/icons/minimap/mini_tank-2.v1"))

    def test_static_files_cannot_leave_the_static_folder(self):
        for path in ("/static/../app.py", "/static/%2e%2e/app.py", "/static/..%2fapp.py", "/static/js/../../app.py", "/static/%2e%2e%2f%2e%2e%2fstore.py"):
            with self.subTest(path=path):
                reply = self.client.get(path)
                self.assertNotIn(b"def create_app", reply.data)
                self.assertNotIn(b"class Store", reply.data)
        self.assertEqual(self.client.get("/static/js/main.js").status_code, 200)

    def test_map_and_font_names_are_checked(self):
        for path in ("/api/maps/../../secret", "/api/maps/..%2f..%2fsecret.png", "/api/maps/%2e%2e/hd.jpg", "/api/fonts/..%2fsecret.png", "/api/fonts/x.png"):
            with self.subTest(path=path):
                reply = self.client.get(path)
                self.assertNotIn(b"TOP-SECRET", reply.data)

    def test_headers_of_every_page(self):
        for path in ("/", "/api/game", "/static/js/main.js", "/nope"):
            h = self.client.get(path).headers
            with self.subTest(path=path):
                self.assertIn("script-src 'self'", h["Content-Security-Policy"])
                self.assertNotIn("unsafe-eval", h["Content-Security-Policy"])
                self.assertNotIn("script-src 'self' 'unsafe-inline'", h["Content-Security-Policy"])
                self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
                self.assertEqual(h["X-Frame-Options"], "DENY")
                self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("<script>", open(os.path.join(os.path.dirname(reader.__file__), "web", "static", "index.html"), encoding="utf-8").read().replace('<script type="module"', ""))

    def test_an_uploaded_name_cannot_write_outside_the_upload_folder(self):
        names = ("../../evil.bf2demo", "..\..\evil.bf2demo", "/tmp/evil.bf2demo", "a/b/c.bf2demo", "x\x00.bf2demo")
        before = set(os.listdir(self.tmp)) | set(os.listdir(self.cache))
        for name in names:
            with self.subTest(name=name):
                reply = self.client.post("/api/upload", data={"file": (io.BytesIO(b"junk"), name)}, content_type="multipart/form-data")
                self.assertIn(reply.status_code, (200, 400))
        self.assertEqual(before | {"uploads"}, set(os.listdir(self.tmp)) | set(os.listdir(self.cache)) | {"uploads"})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.bf2demo")) or os.path.exists(os.path.join(self.cache, "evil.bf2demo")))
        for folder, _, files in os.walk(self.tmp):
            for f in files:
                if f.endswith(".bf2demo"):
                    self.assertTrue(os.path.abspath(folder).startswith(os.path.join(self.cache, "uploads")), os.path.join(folder, f))

    def test_a_broken_recording_does_not_leak_paths(self):
        path = os.path.join(self.demos, "broken.bf2demo")
        with open(path, "wb") as fh:
            fh.write(b"not a recording at all" * 50)
        did = self.client.get("/api/demos").get_json()[0]["id"]
        self.client.get(f"/api/demos/{did}")
        for _ in range(100):                                                                  # the parse runs in a thread
            reply = self.client.get(f"/api/demos/{did}")
            if reply.status_code == 202 and reply.get_json().get("status") == "error":
                break
            import time
            time.sleep(0.05)
        text = reply.get_data(as_text=True)
        self.assertNotIn(self.tmp, text)
        self.assertNotIn("broken.bf2demo", text)
        self.assertNotIn("Traceback", text)

    def test_a_decompression_bomb_is_refused(self):
        old = reader.MAX_INFLATED
        reader.MAX_INFLATED = 1 << 20
        try:
            bomb = zlib.compress(b"\0" * (8 << 20))                                            # 8 MB of zeros in a few KB
            with self.assertRaises(ValueError):
                reader.inflate(bomb)
            self.assertEqual(reader.inflate(zlib.compress(b"x" * 1000))[0], b"x" * 1000)       # a normal stream is untouched
        finally:
            reader.MAX_INFLATED = old


if __name__ == "__main__":
    unittest.main()
