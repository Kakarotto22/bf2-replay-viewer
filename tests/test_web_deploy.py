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
