"""The settings a public server needs: uploads off, a limit on parallel parsing, the WSGI entry that reads its folders from the environment."""

from __future__ import annotations

import importlib
import io
import os
import shutil
import sys
import tempfile
import unittest

from bf2demo.web.app import create_app

from .common import sample_path

SAMPLE = "claude_spawn_115014.bf2demo"


class PublicModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.demos = os.path.join(self.tmp, "demos")
        os.makedirs(self.demos)
        shutil.copy(sample_path(SAMPLE), self.demos)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, **kw):
        return create_app([self.demos], os.path.join(self.tmp, "cache"), **{"donate_file": False, **kw}).test_client()

    def test_upload_is_refused_when_disabled_and_the_page_is_told(self):
        c = self.client(allow_upload=False)
        self.assertFalse(c.get("/api/game").get_json()["upload"])
        reply = c.post("/api/upload", data={"file": (io.BytesIO(b"x"), "a.bf2demo")}, content_type="multipart/form-data")
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(len(c.get("/api/demos").get_json()), 1)           # the published folder is still listed

    def test_upload_stays_available_by_default(self):
        self.assertTrue(self.client().get("/api/game").get_json()["upload"])

    def test_support_section_needs_a_telegram_username(self):
        self.assertIsNone(self.client().get("/api/game").get_json()["donate"])            # hidden until the owner sets it
        for given in ("@my_name", "my_name", "https://t.me/my_name", " t.me/my_name "):
            self.assertEqual(self.client(donate_telegram=given).get("/api/game").get_json()["donate"], {"telegram": "my_name", "methods": []})
        with self.assertRaises(ValueError):                                                # a typo must not publish a dead link
            self.client(donate_telegram="not a name!")

    def test_security_headers(self):
        headers = self.client().get("/").headers
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_wsgi_entry_reads_the_environment(self):
        old = {k: os.environ.get(k) for k in ("BF2VIEW_DEMOS", "BF2VIEW_CACHE", "BF2VIEW_UPLOAD")}
        os.environ.update(BF2VIEW_DEMOS=self.demos, BF2VIEW_CACHE=os.path.join(self.tmp, "c2"))
        os.environ.pop("BF2VIEW_UPLOAD", None)
        try:
            sys.modules.pop("bf2demo.web.wsgi", None)
            module = importlib.import_module("bf2demo.web.wsgi")
            c = module.app.test_client()
            self.assertFalse(c.get("/api/game").get_json()["upload"])       # off unless BF2VIEW_UPLOAD=1
            self.assertEqual(len(c.get("/api/demos").get_json()), 1)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            sys.modules.pop("bf2demo.web.wsgi", None)


if __name__ == "__main__":
    unittest.main()


class AbuseLimitsTest(unittest.TestCase):
    def test_rate_limit_window(self):
        from bf2demo.web.limits import RateLimit
        limit = RateLimit(2, 60)
        self.assertEqual([limit.hit("a", 0), limit.hit("a", 1)], [0, 0])
        self.assertGreater(limit.hit("a", 2), 0)                  # the third within the minute waits
        self.assertEqual(limit.hit("b", 2), 0)                    # another address is not affected
        self.assertEqual(limit.hit("a", 61), 0)                   # the window moved on

    def test_clip_and_upload_answer_429_when_asked_too_often(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        demos = os.path.join(tmp, "demos"); os.makedirs(demos); shutil.copy(sample_path(SAMPLE), demos)
        c = create_app([demos], os.path.join(tmp, "cache"), donate_file=False, clips_per_minute=2, uploads_per_hour=1).test_client()
        did = c.get("/api/demos").get_json()[0]["id"]
        codes = [c.get(f"/api/demos/{did}/clip?end=3000").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        self.assertIn("Retry-After", c.get(f"/api/demos/{did}/clip").headers)
        bad = lambda: c.post("/api/upload", data={"file": (io.BytesIO(b"x"), "a.txt")}, content_type="multipart/form-data").status_code
        self.assertEqual([bad(), bad()], [400, 429])


class EnvFileTest(unittest.TestCase):
    def test_an_env_file_overrides_the_environment_of_the_wsgi_entry(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        envfile = os.path.join(tmp, "bf2view.env")
        with open(envfile, "w", encoding="utf-8") as fh:
            fh.write("# comment\nBF2VIEW_UPLOAD=0\nBF2VIEW_DEMOS=" + tmp + "\nBF2VIEW_CACHE=" + os.path.join(tmp, "c") + "\nOTHER=ignored\n")
        old = {k: os.environ.get(k) for k in ("BF2VIEW_ENV_FILE", "BF2VIEW_UPLOAD", "BF2VIEW_DEMOS", "BF2VIEW_CACHE", "OTHER")}
        os.environ.update(BF2VIEW_ENV_FILE=envfile, BF2VIEW_UPLOAD="1")                       # the service says 1, the file says 0
        try:
            sys.modules.pop("bf2demo.web.wsgi", None)
            module = importlib.import_module("bf2demo.web.wsgi")
            self.assertFalse(module.app.test_client().get("/api/game").get_json()["upload"])
            self.assertNotIn("OTHER", os.environ)                                              # only BF2VIEW_* keys are taken
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            sys.modules.pop("bf2demo.web.wsgi", None)
